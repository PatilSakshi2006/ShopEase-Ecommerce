from django.shortcuts import render, redirect, get_object_or_404
from .models import Product, Order, OrderItem, Wishlist, Profile, Review
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.db import transaction

def product_list(request):
    search = request.GET.get('search', '')
    category = request.GET.get('category', '')

    products = Product.objects.all()

    if search:
        products = products.filter(name__icontains=search)

    if category:
        products = products.filter(category=category)

    categories = Product.CATEGORY_CHOICES

    cart = request.session.get('cart', {})
    cart_count = sum(cart.values())

    return render(request, 'products/product_list.html', {
        'products': products,
        'categories': categories,
        'cart_count': cart_count
    })

def product_detail(request, id):
    product = Product.objects.get(id=id)

    reviews = product.reviews.all().order_by('-created_at')

    return render(request, 'products/product_detail.html', {
        'product': product,
        'reviews': reviews
    })

def add_to_cart(request, id):
    cart = request.session.get('cart', {})

    product = Product.objects.get(id=id)

    product_id = str(id)
    current_quantity = cart.get(product_id, 0)

    if current_quantity < product.stock:
        cart[product_id] = current_quantity + 1

    request.session['cart'] = cart

    from django.shortcuts import redirect
    return redirect('cart')

def cart_view(request):
    cart = request.session.get('cart', {})
    products = Product.objects.filter(id__in=cart.keys())

    cart_items = []
    total = 0

    for product in products:
        quantity = cart[str(product.id)]
        subtotal = product.price * quantity
        total += subtotal

        cart_items.append({
            'product': product,
            'quantity': quantity,
            'subtotal': subtotal
        })

    return render(request, 'products/cart.html', {
        'cart_items': cart_items,
        'total': total
    })



def remove_from_cart(request, id):
    cart = request.session.get('cart', {})
    product_id = str(id)

    if product_id in cart:
        del cart[product_id]

    request.session['cart'] = cart
    return redirect('cart')

def update_cart(request, id):
    cart = request.session.get('cart', {})
    product_id = str(id)

    quantity = int(request.POST.get('quantity', 1))

    product = Product.objects.get(id=id)

    if quantity > product.stock:
        quantity = product.stock

    if quantity > 0:
        cart[product_id] = quantity
    else:
        cart.pop(product_id, None)

    request.session['cart'] = cart

    return redirect('cart')

def checkout(request):
    buy_now = request.session.get('buy_now_product')

    if buy_now:
        cart = {
            str(buy_now['id']): buy_now['quantity']
        }
    else:
        cart = request.session.get('cart', {})

    # Prevent empty or invalid carts
    if not cart:
        return render(request, 'products/checkout.html', {
            'cart_items': [],
            'total': 0,
            'error_message': 'Your cart is empty. Please add a product first.'
        })

    try:
        cart = {
            str(int(product_id)): int(quantity)
            for product_id, quantity in cart.items()
        }

        if any(quantity <= 0 for quantity in cart.values()):
            raise ValueError

    except (ValueError, TypeError):
        return render(request, 'products/checkout.html', {
            'cart_items': [],
            'total': 0,
            'error_message': 'Invalid cart details. Please update your cart.'
        })

    products = list(Product.objects.filter(id__in=cart.keys()))

    if len(products) != len(cart):
        return render(request, 'products/checkout.html', {
            'cart_items': [],
            'total': 0,
            'error_message': 'A product is no longer available. Please update your cart.'
        })

    total = 0
    cart_items = []

    for product in products:
        quantity = cart[str(product.id)]
        subtotal = product.price * quantity
        total += subtotal

        cart_items.append({
            'product': product,
            'quantity': quantity,
            'subtotal': subtotal
        })

    if request.method == 'POST':
        customer_name = request.POST.get('customer_name', '').strip()
        email = request.POST.get('email', '').strip()
        address = request.POST.get('address', '').strip()
        payment_method = request.POST.get('payment_method', 'cod').strip()

        if payment_method != 'cod':
            return render(request, 'products/checkout.html', {
                'cart_items': cart_items,
                'total': total,
                'error_message': 'Please select a valid payment method.'
            })

        if not customer_name or not email or not address:
            return render(request, 'products/checkout.html', {
                'cart_items': cart_items,
                'total': total,
                'error_message': 'Please fill in all delivery details.'
            })

        try:
            with transaction.atomic():
                # Lock product rows while checking and updating stock
                locked_products = list(
                    Product.objects.select_for_update()
                    .filter(id__in=cart.keys())
                    .order_by('id')
                )

                if len(locked_products) != len(cart):
                    raise ValueError(
                        'A product is no longer available. Please update your cart.'
                    )

                # Validate stock before creating the order
                for product in locked_products:
                    quantity = cart[str(product.id)]

                    if quantity > product.stock:
                        raise ValueError(
                            f'Only {product.stock} units of '
                            f'{product.name} are currently available.'
                        )

                # Recalculate total using the current product prices
                total = sum(
                    product.price * cart[str(product.id)]
                    for product in locked_products
                )

                order = Order.objects.create(
                    user=request.user if request.user.is_authenticated else None,
                    customer_name=customer_name,
                    email=email,
                    address=address,
                    total_amount=total,
                    payment_method=payment_method
                )

                for product in locked_products:
                    quantity = cart[str(product.id)]

                    OrderItem.objects.create(
                        order=order,
                        product=product,
                        quantity=quantity,
                        price=product.price
                    )

                    product.stock -= quantity
                    product.save(update_fields=['stock'])

        except ValueError as error:
            return render(request, 'products/checkout.html', {
                'cart_items': cart_items,
                'total': total,
                'error_message': str(error)
            })

        # Clear the correct session data after successful ordering
        if buy_now:
            request.session.pop('buy_now_product', None)
        else:
            request.session['cart'] = {}

        return render(request, 'products/order_success.html', {
            'order': order
        })

    return render(request, 'products/checkout.html', {
        'cart_items': cart_items,
        'total': total
    })

from django.contrib.auth.models import User
from django.contrib.auth import login


def register(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )

        login(request, user)

        return redirect('/')

    return render(request, 'products/register.html')

from django.contrib.auth import authenticate


def user_login(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(
            request,
            username=username,
            password=password
        )

        if user is not None:
            login(request, user)
            return redirect('/')

    return render(request, 'products/login.html')


def user_logout(request):
    logout(request)
    return redirect('/')

@login_required(login_url='user_login')
def my_orders(request):
    orders = Order.objects.filter(
        user=request.user
    ).order_by('-created_at')

    for order in orders:
        for item in order.items.all():
            item.subtotal = item.price * item.quantity

    return render(
        request,
        'products/my_orders.html',
        {'orders': orders}
    )

@login_required(login_url='user_login')
def order_detail(request, id):
    order = get_object_or_404(
        Order,
        id=id,
        user=request.user
    )

    items = order.items.all()

    for item in items:
        item.subtotal = item.price * item.quantity

    return render(
        request,
        'products/order_detail.html',
        {
            'order': order,
            'items': items
        }
    )

def add_to_wishlist(request, id):
    if not request.user.is_authenticated:
        return redirect('user_login')

    product = Product.objects.get(id=id)

    Wishlist.objects.get_or_create(
        user=request.user,
        product=product
    )

    return redirect('wishlist')

def wishlist(request):
    if not request.user.is_authenticated:
        return redirect('user_login')

    wishlist_items = Wishlist.objects.filter(
        user=request.user
    ).select_related('product').order_by('-created_at')

    return render(request, 'products/wishlist.html', {
        'wishlist_items': wishlist_items
    })

def remove_from_wishlist(request, id):
    if not request.user.is_authenticated:
        return redirect('user_login')

    Wishlist.objects.filter(
        user=request.user,
        product_id=id
    ).delete()

    return redirect('wishlist')

@login_required(login_url='user_login')
def profile(request):
    profile, created = Profile.objects.get_or_create(
        user=request.user
    )

    return render(
        request,
        'products/profile.html',
        {'profile': profile}
    )

@login_required(login_url='user_login')
def edit_profile(request):
    profile, created = Profile.objects.get_or_create(
        user=request.user
    )

    if request.method == 'POST':
        profile.phone = request.POST.get('phone', '').strip()
        profile.address = request.POST.get('address', '').strip()
        profile.city = request.POST.get('city', '').strip()
        profile.pincode = request.POST.get('pincode', '').strip()

        profile.save()
        return redirect('profile')

    return render(
        request,
        'products/edit_profile.html',
        {'profile': profile}
    )

def add_review(request, id):
    if not request.user.is_authenticated:
        return redirect('user_login')

    product = Product.objects.get(id=id)

    if request.method == 'POST':
        rating = int(request.POST.get('rating', 5))
        comment = request.POST.get('comment')

        if rating < 1:
            rating = 1

        if rating > 5:
            rating = 5

        Review.objects.create(
            user=request.user,
            product=product,
            rating=rating,
            comment=comment
        )

        return redirect('product_detail', id=id)

    return redirect('product_detail', id=id)
def buy_now(request, id):
    product = Product.objects.get(id=id)

    if product.stock <= 0:
        return redirect('product_detail', id=id)

    request.session['buy_now_product'] = {
        'id': product.id,
        'quantity': 1
    }

    return redirect('checkout')




# Create your views here.

import csv
from django.contrib import admin
from django.contrib.auth.models import User
from django.utils.html import format_html
from django.db.models import Sum, F
from django.db.models import Count
from django.db.models.functions import TruncMonth
from .models import Product, Review, Order, OrderItem
from django.http import HttpResponse

def get_total_sales():
    total = Order.objects.aggregate(
        total=Sum('total_amount')
    )['total'] or 0

    return f"{total:,.2f}"

def get_order_stats():
    total_orders = Order.objects.count()
    return {
        'total_products': Product.objects.count(),
        'total_users': User.objects.count(),
        'low_stock_products': Product.objects.filter(stock__lte=5, stock__gt=0).count(),
        'pending_orders': Order.objects.filter(status='Pending').count(),
        'shipped_orders': Order.objects.filter(status='Shipped').count(),
        'delivered_orders': Order.objects.filter(status='Delivered').count(),
        'cancelled_orders': Order.objects.filter(status='Cancelled').count(),
        'total_orders': total_orders,
        'average_order_value': (
             Order.objects.aggregate(total=Sum('total_amount'))['total'] / total_orders
        ) if total_orders else 0,
        'pending_percent': (Order.objects.filter(status='Pending').count() / total_orders * 100) if total_orders else 0,
        'shipped_percent': (Order.objects.filter(status='Shipped').count() / total_orders * 100) if total_orders else 0,
        'delivered_percent': (Order.objects.filter(status='Delivered').count() / total_orders * 100) if total_orders else 0,
        'cancelled_percent': (Order.objects.filter(status='Cancelled').count() / total_orders * 100) if total_orders else 0,
    }

    
def get_top_selling_products():
    return (
        OrderItem.objects
        .values('product__name')
        .annotate(total_sold=Sum('quantity'))
        .order_by('-total_sold')[:5]
    )

def get_monthly_sales():
    return (
        Order.objects
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(total_sales=Sum('total_amount'))
        .order_by('-month')[:12]
    )
    


def get_product_sales_analytics():
    return (
        OrderItem.objects
        .values('product__name')
        .annotate(
            total_sold=Sum('quantity'),
            total_revenue=Sum(F('price') * F('quantity'))
        )
        .order_by('-total_revenue')
    )


def export_orders_csv(modeladmin, request, queryset):
    response = __import__('django.http', fromlist=['HttpResponse']).HttpResponse(
        content_type='text/csv'
    )
    response['Content-Disposition'] = 'attachment; filename="shopease_orders.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Order ID',
        'Customer Name',
        'Email',
        'Total Amount',
        'Status',
        'Order Date'
    ])

    for order in queryset:
        writer.writerow([
            order.id,
            order.customer_name,
            order.email,
            order.total_amount,
            order.status,
            order.created_at.strftime('%d-%m-%Y %H:%M')
        ])

    return response

export_orders_csv.short_description = 'Export selected orders to CSV'


def export_products_csv(modeladmin, request, queryset):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="shopease_products.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Product ID',
        'Product Name',
        'Category',
        'Price',
        'Stock'
    ])

    for product in queryset:
        writer.writerow([
            product.id,
            product.name,
            product.category,
            product.price,
            product.stock
        ])

    return response

export_products_csv.short_description = 'Export selected products to CSV'

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0

# Price Range Filter
class PriceRangeFilter(admin.SimpleListFilter):
    title = 'Price Range'
    parameter_name = 'price_range'

    def lookups(self, request, model_admin):
        return [
            ('under500', 'Under ₹500'),
            ('500to1000', '₹500 – ₹1,000'),
            ('1000to5000', '₹1,000 – ₹5,000'),
            ('above5000', 'Above ₹5,000'),
        ]

    def queryset(self, request, queryset):
        value = self.value()

        if value == 'under500':
            return queryset.filter(price__lt=500)
        elif value == '500to1000':
            return queryset.filter(price__gte=500, price__lte=1000)
        elif value == '1000to5000':
            return queryset.filter(price__gt=1000, price__lte=5000)
        elif value == 'above5000':
            return queryset.filter(price__gt=5000)

        return queryset

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    actions = [export_products_csv]
    list_display = (
        'id',
        'image_preview',
        'name',
        'category',
        'price',
        'stock',
        'stock_status',
        'created_at'
    )
    search_fields = ('name', 'category')
    list_filter = ('category', 'stock', PriceRangeFilter)
    list_editable = ('price', 'stock')
    list_per_page = 10
    ordering = ('-created_at',)



    @admin.display(description='Stock Status')
    def stock_status(self, obj):
        if obj.stock == 0:
            return '❌ Out of Stock'
        elif obj.stock <= 5:
            return '⚠️ Low Stock'
        else:
            return '✅ In Stock'

    @admin.display(description='Image')
    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" width="60" height="60" style="object-fit: cover; border-radius: 8px;">',
                obj.image.url
        )
        return 'No Image' 
       
admin.site.register(Review)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    actions = [export_orders_csv]
    change_list_template = 'admin/orders_change_list.html'
    list_display = ('id', 'customer_name', 'email', 'total_amount', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('customer_name', 'email')
    inlines = [OrderItemInline]

    def changelist_view(self, request, extra_context=None):
        stats = get_order_stats()

        extra_context = extra_context or {}
        extra_context.update(stats)
        extra_context['total_sales'] = get_total_sales()
        extra_context['recent_orders'] = Order.objects.order_by('-created_at')[:5]
        extra_context['top_selling_products'] = get_top_selling_products()
        extra_context['product_sales_analytics'] = get_product_sales_analytics()
        extra_context['monthly_sales'] = get_monthly_sales()
        extra_context['low_stock_products_list'] = Product.objects.filter(stock__lte=5, stock__gt=0).order_by('stock')


        return super().changelist_view(
            request,
            extra_context=extra_context
        )   


admin.site.register(OrderItem)
# Register your models here.

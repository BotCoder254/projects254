// Initialize Socket.IO connection
const socket = io();

// Real-time updates for dashboard
socket.on('stats_update', function(data) {
    // Update dashboard stats
    updateDashboardStats(data);
});

socket.on('new_order', function(data) {
    // Add new order to recent orders list
    addRecentOrder(data);
    // Update order count and revenue
    updateOrderStats(data);
});

socket.on('order_status_update', function(data) {
    // Update order status in orders table
    updateOrderStatus(data);
    // Update dashboard if on dashboard page
    if (document.getElementById('dashboard-stats')) {
        updateDashboardStats(data);
    }
});

// Dashboard functions
function updateDashboardStats(data) {
    const stats = document.getElementById('dashboard-stats');
    if (!stats) return;

    // Update total orders
    const totalOrders = stats.querySelector('[data-stat="total-orders"]');
    if (totalOrders) totalOrders.textContent = data.total_orders;

    // Update revenue
    const revenue = stats.querySelector('[data-stat="revenue"]');
    if (revenue) revenue.textContent = `$${data.total_revenue.toFixed(2)}`;

    // Update active users
    const activeUsers = stats.querySelector('[data-stat="active-users"]');
    if (activeUsers) activeUsers.textContent = data.active_users;

    // Update menu items
    const menuItems = stats.querySelector('[data-stat="menu-items"]');
    if (menuItems) menuItems.textContent = data.menu_items;
}

function addRecentOrder(order) {
    const recentOrders = document.getElementById('recent-orders');
    if (!recentOrders) return;

    const orderHtml = `
        <div class="flex items-center justify-between">
            <div class="flex items-center">
                <div class="w-10 h-10 rounded-full bg-gray-100 flex items-center justify-center">
                    <i class="fas fa-receipt text-gray-600"></i>
                </div>
                <div class="ml-4">
                    <p class="text-sm font-medium text-gray-900">Order #${order.order_id}</p>
                    <p class="text-xs text-gray-600">${new Date(order.created_at).toLocaleDateString()}</p>
                </div>
            </div>
            <div class="text-right">
                <p class="text-sm font-medium text-gray-900">$${order.total.toFixed(2)}</p>
                <span class="text-xs px-2 py-1 rounded-full bg-blue-100 text-blue-800">
                    ${order.status}
                </span>
            </div>
        </div>
    `;

    // Add to the top of the list
    const firstOrder = recentOrders.firstChild;
    const orderDiv = document.createElement('div');
    orderDiv.innerHTML = orderHtml;
    recentOrders.insertBefore(orderDiv.firstChild, firstOrder);

    // Remove last order if more than 5
    if (recentOrders.children.length > 5) {
        recentOrders.removeChild(recentOrders.lastChild);
    }
}

// Menu management functions
function refreshMenuItems() {
    fetch('/api/admin/menu')
        .then(response => response.json())
        .then(items => {
            const menuGrid = document.getElementById('menu-items-grid');
            if (!menuGrid) return;
            
            menuGrid.innerHTML = items.map(item => `
                <div class="bg-white rounded-xl shadow-sm overflow-hidden">
                    <!-- Menu item template -->
                </div>
            `).join('');
        });
}

// Order management functions
function updateOrderStatus(data) {
    const orderRow = document.getElementById(`order-${data.order_id}`);
    if (!orderRow) return;

    const statusSelect = orderRow.querySelector('select');
    if (statusSelect) {
        statusSelect.value = data.status;
        updateStatusSelectStyle(statusSelect);
    }
}

// Analytics functions
function updateAnalytics(data) {
    // Update charts and statistics
    if (window.salesChart) {
        window.salesChart.data.datasets[0].data = data.sales;
        window.salesChart.update();
    }
}

// Initialize tooltips and other UI elements
document.addEventListener('DOMContentLoaded', function() {
    // Initialize any third-party plugins or UI components
    initializeTooltips();
    initializeDropdowns();
});

// Helper functions
function initializeTooltips() {
    // Initialize tooltips if using a UI library
}

function initializeDropdowns() {
    // Initialize dropdowns if using a UI library
}

function updateStatusSelectStyle(select) {
    select.className = 'text-sm rounded-full px-3 py-1';
    const status = select.value;
    const statusClasses = {
        'confirmed': 'bg-gray-100 text-gray-800',
        'preparing': 'bg-yellow-100 text-yellow-800',
        'out_for_delivery': 'bg-blue-100 text-blue-800',
        'delivered': 'bg-green-100 text-green-800'
    };
    select.classList.add(...statusClasses[status].split(' '));
}

// Export functions for use in other scripts
window.adminFunctions = {
    refreshMenuItems,
    updateOrderStatus,
    updateAnalytics
}; 
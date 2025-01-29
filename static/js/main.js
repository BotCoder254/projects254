// Toast notification function
function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `fixed bottom-4 right-4 px-6 py-3 rounded-lg text-white ${
        type === 'success' ? 'bg-green-500' : 'bg-red-500'
    } transition-opacity duration-300`;
    toast.textContent = message;
    
    document.body.appendChild(toast);
    
    // Fade out and remove after 3 seconds
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => {
            document.body.removeChild(toast);
        }, 300);
    }, 3000);
}

// Form validation
document.addEventListener('DOMContentLoaded', function() {
    const forms = document.querySelectorAll('form');
    
    forms.forEach(form => {
        const emailInput = form.querySelector('input[type="email"]');
        const passwordInput = form.querySelector('input[type="password"]');
        
        if (emailInput) {
            emailInput.addEventListener('input', function() {
                const isValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(this.value);
                this.classList.toggle('border-red-500', !isValid);
                this.classList.toggle('border-green-500', isValid);
            });
        }
        
        if (passwordInput) {
            passwordInput.addEventListener('input', function() {
                const isStrong = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$/.test(this.value);
                this.classList.toggle('border-red-500', !isStrong);
                this.classList.toggle('border-green-500', isStrong);
            });
        }
    });
});

// Smooth scroll
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function(e) {
        const href = this.getAttribute('href');
        // Only handle smooth scroll for fragment identifiers that are not just '#'
        if (href && href !== '#') {
            e.preventDefault();
            const target = document.querySelector(href);
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        }
    });
});

// Mobile menu toggle
const mobileMenuButton = document.querySelector('[data-mobile-menu]');
const mobileMenu = document.querySelector('[data-mobile-menu-items]');

if (mobileMenuButton && mobileMenu) {
    mobileMenuButton.addEventListener('click', () => {
        mobileMenu.classList.toggle('hidden');
    });
}

// Add to cart functionality
function addToCart(itemId, itemName, price, imageUrl) {
    // Get quantity if it exists, otherwise default to 1
    const quantityInput = document.getElementById(`quantity-${itemId}`);
    const quantity = quantityInput ? parseInt(quantityInput.value) : 1;
    
    // Create cart item
    const cartItem = {
        id: itemId,
        name: itemName,
        price: parseFloat(price),
        quantity: quantity,
        image_url: imageUrl
    };
    
    // Add to backend first
    fetch('/api/cart/add', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(cartItem)
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            // Get existing cart from localStorage or initialize empty array
            let cart = JSON.parse(localStorage.getItem('cart') || '[]');
            
            // Check if item already exists in cart
            const existingItem = cart.find(item => item.id === itemId);
            
            if (existingItem) {
                existingItem.quantity += quantity;
            } else {
                cart.push(cartItem);
            }
            
            // Save updated cart to localStorage
            localStorage.setItem('cart', JSON.stringify(cart));
            
            // Update cart count immediately
            updateCartCount();
            
            // Show success message
            showToast(`${quantity} x ${itemName} added to cart!`);
            
            // Emit cart update event
            if (typeof socket !== 'undefined') {
                socket.emit('cart_update', { cart: cart });
            }
        } else {
            showToast('Error adding item to cart', 'error');
        }
    })
    .catch(error => {
        console.error('Error adding to cart:', error);
        showToast('Error adding item to cart', 'error');
    });
}

// Initialize cart count on page load
document.addEventListener('DOMContentLoaded', function() {
    // Initialize Socket.IO
    if (typeof io !== 'undefined') {
        window.socket = io();
        
        // Listen for cart updates
        socket.on('cart_update', function(data) {
            if (data.cart) {
                localStorage.setItem('cart', JSON.stringify(data.cart));
                updateCartCount();
                // If we're on the cart page or payment history page, update the UI
                const currentPath = window.location.pathname;
                if (currentPath === '/cart' || currentPath === '/payment-history') {
                    window.location.reload();
                }
            }
        });
        
        // Listen for order updates
        socket.on('order_update', function(data) {
            if (data.action === 'receipt_downloaded') {
                // Refresh the page to update receipt download status
                if (window.location.pathname === '/payment-history') {
                    location.reload();
                }
            }
        });
    }
    
    // Load initial cart data
    fetch('/api/cart')
    .then(response => response.json())
    .then(cart => {
        if (Array.isArray(cart)) {
            localStorage.setItem('cart', JSON.stringify(cart));
            updateCartCount();
            
            // Sync with server if there's a difference
            const localCart = JSON.parse(localStorage.getItem('cart') || '[]');
            if (JSON.stringify(localCart) !== JSON.stringify(cart)) {
                fetch('/api/cart/sync', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(localCart)
                });
            }
        }
    })
    .catch(error => {
        console.error('Error loading cart:', error);
    });
    
    // Handle navigation links
    document.querySelectorAll('a[href]').forEach(link => {
        link.addEventListener('click', function(e) {
            const href = this.getAttribute('href');
            // Don't interfere with fragment identifiers or external links
            if (href && !href.startsWith('#') && !href.startsWith('http')) {
                // Normal navigation will proceed
                return;
            }
        });
    });
});

// Update cart count in UI
function updateCartCount() {
    const cart = JSON.parse(localStorage.getItem('cart') || '[]');
    const totalItems = cart.reduce((sum, item) => sum + (parseInt(item.quantity) || 0), 0);
    const cartCount = document.querySelector('[data-cart-count]');
    
    if (cartCount) {
        if (totalItems > 0) {
            cartCount.textContent = totalItems;
            cartCount.classList.remove('hidden');
        } else {
            cartCount.textContent = '';
            cartCount.classList.add('hidden');
        }
    }
} 
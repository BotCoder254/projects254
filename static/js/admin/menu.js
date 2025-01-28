// Menu Management JavaScript

let currentItemId = null;

// Direct function declarations for onclick handlers
window.openAddModal = function() {
    currentItemId = null;
    const modal = document.getElementById('itemModal');
    const form = document.getElementById('itemForm');
    const title = document.getElementById('modalTitle');
    
    if (modal && form && title) {
        title.textContent = 'Add Menu Item';
        form.reset();
        clearImagePreviews();
        updatePreview();
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    }
};

window.closeItemModal = function() {
    const modal = document.getElementById('itemModal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        clearImagePreviews();
    }
};

window.closeDeleteModal = function() {
    const modal = document.getElementById('deleteConfirmModal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
};

window.confirmDelete = function() {
    if (!currentItemId) return;
    
    fetch(`/api/admin/menu/${currentItemId}`, {
        method: 'DELETE'
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showAlert('Successfully deleted item', 'success');
            closeDeleteModal();
            location.reload();
        } else {
            showAlert(data.error || 'An error occurred', 'error');
        }
    })
    .catch(error => {
        showAlert('Error deleting item', 'error');
        console.error('Error:', error);
    });
};

window.editItem = function(itemId) {
    currentItemId = itemId;
    
    fetch(`/api/admin/menu/${itemId}`)
        .then(response => response.json())
        .then(item => {
            document.getElementById('modalTitle').textContent = 'Edit Menu Item';
            document.getElementById('itemName').value = item.name;
            document.getElementById('itemDescription').value = item.description;
            document.getElementById('itemPrice').value = item.price;
            document.getElementById('itemCategory').value = item.category;
            document.getElementById('itemStatus').value = item.active.toString();
            
            // Handle images
            const container = document.getElementById('imagePreviewContainer');
            container.innerHTML = '';
            if (item.images && item.images.length > 0) {
                item.images.forEach(image => {
                    const preview = document.createElement('div');
                    preview.className = 'relative aspect-square';
                    preview.innerHTML = `
                        <img src="${image}" class="w-full h-full object-cover rounded-lg">
                        <button type="button" onclick="removeImage(this)" class="absolute top-1 right-1 bg-red-500 text-white rounded-full w-6 h-6 flex items-center justify-center">
                            <i class="fas fa-times"></i>
                        </button>
                    `;
                    container.appendChild(preview);
                });
                
                // Set first image as main preview
                document.getElementById('previewImage').style.backgroundImage = `url(${item.images[0]})`;
            }
            
            updatePreview();
            openAddModal();
        })
        .catch(error => {
            showAlert('Error loading item details', 'error');
            console.error('Error:', error);
        });
};

window.deleteItem = function(itemId) {
    currentItemId = itemId;
    
    // Check if item has active orders
    fetch(`/api/admin/menu/${itemId}/check-orders`)
        .then(response => response.json())
        .then(data => {
            const warning = document.getElementById('deleteWarning');
            if (data.active_orders > 0) {
                warning.textContent = `This item is part of ${data.active_orders} active orders.`;
                warning.classList.remove('hidden');
            } else {
                warning.classList.add('hidden');
            }
            
            document.getElementById('deleteConfirmModal').classList.remove('hidden');
            document.getElementById('deleteConfirmModal').classList.add('flex');
        })
        .catch(error => {
            showAlert('Error checking item orders', 'error');
            console.error('Error:', error);
        });
};

window.bulkAction = function(action) {
    const selectedItems = Array.from(document.querySelectorAll('input[name="item_select"]:checked'))
        .map(checkbox => checkbox.value);
    
    if (selectedItems.length === 0) {
        showAlert('Please select items to perform this action', 'warning');
        return;
    }
    
    if (action === 'delete' && !confirm('Are you sure you want to delete the selected items?')) {
        return;
    }
    
    fetch('/api/admin/menu/bulk-action', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            item_ids: selectedItems,
            action: action
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showAlert(`Successfully ${action}d selected items`, 'success');
            location.reload();
        } else {
            showAlert(data.error || 'An error occurred', 'error');
        }
    })
    .catch(error => {
        showAlert('An error occurred while performing the action', 'error');
        console.error('Error:', error);
    });
};

window.removeImage = function(button) {
    const preview = button.parentElement;
    const container = preview.parentElement;
    container.removeChild(preview);
    updatePreview();
};

document.addEventListener('DOMContentLoaded', function() {
    // Initialize Socket.IO connection
    const socket = io();
    socket.on('connect', () => {
        socket.emit('user_connect');
    });

    // Handle real-time menu updates
    socket.on('menu_update', (data) => {
        updateMenuStats(data.stats);
    });

    // Initialize form submission handler
    const itemForm = document.getElementById('itemForm');
    if (itemForm) {
        itemForm.addEventListener('submit', handleItemSubmit);
    }

    // Initialize search input
    const searchInput = document.getElementById('menuSearch');
    if (searchInput) {
        searchInput.addEventListener('input', debounce(handleSearch, 300));
    }

    // Initialize category filter
    const categoryFilter = document.getElementById('categoryFilter');
    if (categoryFilter) {
        categoryFilter.addEventListener('change', handleSearch);
    }

    // Initialize select all checkbox
    const selectAll = document.getElementById('selectAll');
    if (selectAll) {
        selectAll.addEventListener('change', function() {
            const checkboxes = document.querySelectorAll('input[name="item_select"]');
            checkboxes.forEach(checkbox => checkbox.checked = this.checked);
        });
    }

    // Initialize image upload
    const imageInput = document.getElementById('itemImages');
    if (imageInput) {
        imageInput.addEventListener('change', handleImageUpload);
    }

    // Initialize preview inputs
    ['itemName', 'itemDescription', 'itemPrice', 'itemCategory'].forEach(id => {
        const input = document.getElementById(id);
        if (input) {
            input.addEventListener('input', updatePreview);
        }
    });
});

function initializeEventListeners() {
    // Add menu button
    const addButton = document.querySelector('button[onclick*="openAddModal"]');
    if (addButton) {
        addButton.onclick = function(e) {
            e.preventDefault();
            openAddModal();
        };
    }

    // Bulk action buttons
    const bulkButtons = document.querySelectorAll('button[onclick*="bulkAction"]');
    bulkButtons.forEach(button => {
        const action = button.getAttribute('onclick').match(/'(\w+)'/)[1];
        button.onclick = function(e) {
            e.preventDefault();
            handleBulkAction(action);
        };
    });

    // Individual action buttons
    document.querySelectorAll('button[onclick*="editItem"], button[onclick*="deleteItem"]').forEach(button => {
        const [func, itemId] = button.getAttribute('onclick').match(/(\w+)\('([^']+)'/);
        button.onclick = function(e) {
            e.preventDefault();
            if (func === 'editItem') {
                editItem(itemId);
            } else if (func === 'deleteItem') {
                deleteItem(itemId);
            }
        };
    });

    // Search form
    const searchInput = document.getElementById('menuSearch');
    if (searchInput) {
        searchInput.addEventListener('input', debounce(handleSearch, 300));
    }

    // Category filter
    const categoryFilter = document.getElementById('categoryFilter');
    if (categoryFilter) {
        categoryFilter.addEventListener('change', handleSearch);
    }

    // Select all checkbox
    const selectAll = document.getElementById('selectAll');
    if (selectAll) {
        selectAll.addEventListener('change', function() {
            const checkboxes = document.querySelectorAll('input[name="item_select"]');
            checkboxes.forEach(checkbox => checkbox.checked = this.checked);
        });
    }

    // Item form
    const itemForm = document.getElementById('itemForm');
    if (itemForm) {
        itemForm.addEventListener('submit', handleItemSubmit);
    }

    // Modal close buttons
    const closeButtons = document.querySelectorAll('button[onclick*="closeItemModal"], button[onclick*="closeDeleteModal"]');
    closeButtons.forEach(button => {
        const func = button.getAttribute('onclick').includes('closeItemModal') ? closeItemModal : closeDeleteModal;
        button.onclick = function(e) {
            e.preventDefault();
            func();
        };
    });

    // Image input
    const imageInput = document.getElementById('itemImages');
    if (imageInput) {
        imageInput.addEventListener('change', handleImageUpload);
    }

    // Live preview listeners
    const previewInputs = ['itemName', 'itemDescription', 'itemPrice', 'itemCategory'].map(id => document.getElementById(id));
    previewInputs.forEach(input => {
        if (input) {
            input.addEventListener('input', updatePreview);
        }
    });
}

// Form handling
function handleItemSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const formData = new FormData(form);
    
    const url = currentItemId ? 
        `/api/admin/menu/${currentItemId}` : 
        '/api/admin/menu';
    
    fetch(url, {
        method: currentItemId ? 'PUT' : 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showAlert(`Successfully ${currentItemId ? 'updated' : 'added'} menu item`, 'success');
            closeItemModal();
            location.reload();
        } else {
            showAlert(data.error || 'An error occurred', 'error');
        }
    })
    .catch(error => {
        showAlert('An error occurred while saving the item', 'error');
        console.error('Error:', error);
    });
}

// Image handling
function handleImageUpload(event) {
    const files = event.target.files;
    const container = document.getElementById('imagePreviewContainer');
    const preview = document.getElementById('previewImage');
    
    if (container && files.length > 0) {
        container.innerHTML = '';
        Array.from(files).forEach((file, index) => {
            const reader = new FileReader();
            reader.onload = function(e) {
                const preview = document.createElement('div');
                preview.className = 'relative aspect-square';
                preview.innerHTML = `
                    <img src="${e.target.result}" class="w-full h-full object-cover rounded-lg">
                    <button type="button" onclick="removeImage(this)" class="absolute top-1 right-1 bg-red-500 text-white rounded-full w-6 h-6 flex items-center justify-center">
                        <i class="fas fa-times"></i>
                    </button>
                `;
                container.appendChild(preview);
                
                // Set first image as main preview
                if (index === 0 && preview) {
                    preview.style.backgroundImage = `url(${e.target.result})`;
                }
            };
            reader.readAsDataURL(file);
        });
    }
    updatePreview();
}

function clearImagePreviews() {
    const container = document.getElementById('imagePreviewContainer');
    const preview = document.getElementById('previewImage');
    if (container) container.innerHTML = '';
    if (preview) preview.style.backgroundImage = '';
}

// Preview updates
function updatePreview() {
    const nameInput = document.getElementById('itemName');
    const descInput = document.getElementById('itemDescription');
    const priceInput = document.getElementById('itemPrice');
    const categoryInput = document.getElementById('itemCategory');
    
    const previewName = document.getElementById('previewName');
    const previewDesc = document.getElementById('previewDescription');
    const previewPrice = document.getElementById('previewPrice');
    const previewCategory = document.getElementById('previewCategory');
    
    if (previewName) previewName.textContent = nameInput.value || 'Item Name';
    if (previewDesc) previewDesc.textContent = descInput.value || 'Description will appear here';
    if (previewPrice) previewPrice.textContent = priceInput.value ? `$${parseFloat(priceInput.value).toFixed(2)}` : '$0.00';
    if (previewCategory) previewCategory.textContent = categoryInput.value || 'Category';
}

// Stats update
function updateMenuStats(stats) {
    const elements = {
        'total-items': stats.total_items,
        'active-items': stats.active_items,
        'categories-count': stats.categories,
        'top-seller': `${stats.top_seller_name} (${stats.top_seller_orders} orders)`
    };
    
    Object.entries(elements).forEach(([id, value]) => {
        const element = document.getElementById(id);
        if (element) element.textContent = value;
    });
}

// Utility functions
function showAlert(message, type) {
    const alertDiv = document.createElement('div');
    alertDiv.className = `fixed top-4 right-4 p-4 rounded shadow-lg ${
        type === 'success' ? 'bg-green-500' :
        type === 'error' ? 'bg-red-500' :
        'bg-yellow-500'
    } text-white z-50`;
    alertDiv.textContent = message;
    document.body.appendChild(alertDiv);
    setTimeout(() => alertDiv.remove(), 3000);
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Handle bulk actions
function handleBulkAction(action) {
    const selectedItems = Array.from(document.querySelectorAll('input[name="item_select"]:checked'))
        .map(checkbox => checkbox.value);
    
    if (selectedItems.length === 0) {
        showAlert('Please select items to perform this action', 'warning');
        return;
    }
    
    if (action === 'delete' && !confirm('Are you sure you want to delete the selected items?')) {
        return;
    }
    
    fetch('/api/admin/menu/bulk-action', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            item_ids: selectedItems,
            action: action
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showAlert(`Successfully ${action}d selected items`, 'success');
            location.reload();
        } else {
            showAlert(data.error || 'An error occurred', 'error');
        }
    })
    .catch(error => {
        showAlert('An error occurred while performing the action', 'error');
        console.error('Error:', error);
    });
}

// Search and filter functions
function handleSearch(event) {
    event.preventDefault();
    const searchQuery = document.getElementById('menuSearch').value;
    const categoryFilter = document.getElementById('categoryFilter').value;
    
    const params = new URLSearchParams({
        q: searchQuery,
        category: categoryFilter
    });
    
    fetch(`/api/admin/menu/search?${params}`)
        .then(response => response.json())
        .then(data => {
            updateMenuTable(data);
        })
        .catch(error => {
            showAlert('An error occurred while searching', 'error');
            console.error('Error:', error);
        });
}

// Update menu table with search results
function updateMenuTable(items) {
    const tableBody = document.querySelector('#menu-table tbody');
    tableBody.innerHTML = '';
    
    items.forEach(item => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td class="px-4 py-2">
                <input type="checkbox" name="item_select" value="${item._id}" class="rounded">
            </td>
            <td class="px-4 py-2">
                <img src="${item.images[0] || '/static/images/placeholder.png'}" alt="${item.name}" class="w-16 h-16 object-cover rounded">
            </td>
            <td class="px-4 py-2">${item.name}</td>
            <td class="px-4 py-2">${item.category}</td>
            <td class="px-4 py-2">$${item.price.toFixed(2)}</td>
            <td class="px-4 py-2">
                <span class="px-2 py-1 rounded ${item.active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}">
                    ${item.active ? 'Active' : 'Inactive'}
                </span>
            </td>
            <td class="px-4 py-2">
                <button onclick="handleItemAction('${item._id}', 'edit')" class="text-blue-600 hover:text-blue-800">Edit</button>
                <button onclick="handleItemAction('${item._id}', 'delete')" class="text-red-600 hover:text-red-800 ml-2">Delete</button>
            </td>
        `;
        tableBody.appendChild(row);
    });
}

// Handle individual item actions
function handleItemAction(itemId, action) {
    if (action === 'delete' && !confirm('Are you sure you want to delete this item?')) {
        return;
    }
    
    const url = action === 'delete' 
        ? `/api/admin/menu/${itemId}`
        : `/api/admin/menu/${itemId}`;
    
    const method = action === 'delete' ? 'DELETE' : 'PUT';
    const body = action === 'delete' ? null : JSON.stringify({
        active: action === 'activate'
    });
    
    fetch(url, {
        method: method,
        headers: {
            'Content-Type': 'application/json',
        },
        body: body
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showAlert(`Successfully ${action}d item`, 'success');
            location.reload();
        } else {
            showAlert(data.error || 'An error occurred', 'error');
        }
    })
    .catch(error => {
        showAlert('An error occurred while performing the action', 'error');
        console.error('Error:', error);
    });
} 
// Menu Management JavaScript

// Initialize socket connection
let currentItemId = null;
let socket = io();

// Socket.IO event listeners
socket.on('menu_update', function(data) {
    if (data.stats) {
        document.getElementById('total-items').textContent = data.stats.total_items;
        document.getElementById('active-items').textContent = data.stats.active_items;
        document.getElementById('total-categories').textContent = data.stats.categories;
        document.getElementById('top-seller').textContent = data.stats.top_seller_orders;
    }
    
    if (data.item) {
        const itemRow = document.querySelector(`tr[data-item-id="${data.item._id}"]`);
        if (itemRow) {
            updateItemRow(itemRow, data.item);
        }
    }
});

// Expose functions to window object for onclick handlers
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
                document.getElementById('previewImage').style.backgroundImage = `url(${item.images[0]})`;
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
            }
            
            updatePreview();
            document.getElementById('itemModal').classList.remove('hidden');
            document.getElementById('itemModal').classList.add('flex');
        })
        .catch(error => {
            showAlert('Error loading item details', 'error');
            console.error('Error:', error);
        });
};

window.deleteItem = function(itemId) {
    currentItemId = itemId;
    
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

window.filterItems = function() {
    const query = document.getElementById('menuSearch').value;
    const category = document.getElementById('categoryFilter').value;
    
    fetch(`/api/admin/menu/search?q=${query}&category=${category}`)
        .then(response => response.json())
        .then(data => {
            updateMenuTable(data);
        })
        .catch(error => {
            showAlert('An error occurred while filtering', 'error');
            console.error('Error:', error);
        });
};

window.handleImageUpload = function(event) {
    const files = event.target.files;
    const container = document.getElementById('imagePreviewContainer');
    container.innerHTML = '';
    
    Array.from(files).forEach((file, index) => {
        if (index === 0) {
            // Set first image as preview image
            const previewImage = document.getElementById('previewImage');
            previewImage.style.backgroundImage = `url(${URL.createObjectURL(file)})`;
        }
        
        const preview = document.createElement('div');
        preview.className = 'relative aspect-square';
        preview.innerHTML = `
            <img src="${URL.createObjectURL(file)}" class="w-full h-full object-cover rounded-lg">
            <button type="button" onclick="removeImage(this)" class="absolute top-1 right-1 bg-red-500 text-white rounded-full w-6 h-6 flex items-center justify-center">
                <i class="fas fa-times"></i>
            </button>
        `;
        container.appendChild(preview);
    });
};

window.removeImage = function(button) {
    const preview = button.parentElement;
    preview.remove();
};

// Initialize event listeners when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    // Form submission
    const form = document.getElementById('itemForm');
    if (form) {
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const formData = new FormData(this);
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
                    showAlert('Successfully ' + (currentItemId ? 'updated' : 'added') + ' menu item', 'success');
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
        });
    }

    // Live preview handlers
    ['itemName', 'itemDescription', 'itemPrice', 'itemCategory'].forEach(id => {
        const element = document.getElementById(id);
        if (element) {
            element.addEventListener('input', updatePreview);
        }
    });

    // Search input
    const searchInput = document.getElementById('menuSearch');
    if (searchInput) {
        searchInput.addEventListener('input', debounce(function(e) {
            const query = e.target.value;
            const category = document.getElementById('categoryFilter').value;
            
            fetch(`/api/admin/menu/search?q=${query}&category=${category}`)
                .then(response => response.json())
                .then(data => {
                    updateMenuTable(data);
                })
                .catch(error => {
                    showAlert('An error occurred while searching', 'error');
                    console.error('Error:', error);
                });
        }, 300));
    }

    // Select all checkbox
    const selectAll = document.getElementById('selectAll');
    if (selectAll) {
        selectAll.addEventListener('change', function(e) {
            const checkboxes = document.querySelectorAll('input[name="item_select"]');
            checkboxes.forEach(checkbox => checkbox.checked = e.target.checked);
        });
    }
});

// Utility functions
function updatePreview() {
    document.getElementById('previewName').textContent = document.getElementById('itemName').value || 'Item Name';
    document.getElementById('previewDescription').textContent = document.getElementById('itemDescription').value || 'Description will appear here';
    document.getElementById('previewPrice').textContent = '$' + (parseFloat(document.getElementById('itemPrice').value) || 0).toFixed(2);
    document.getElementById('previewCategory').textContent = document.getElementById('itemCategory').value || 'Category';
}

function updateMenuTable(items) {
    const tbody = document.querySelector('tbody');
    tbody.innerHTML = items.map(item => `
        <tr class="hover:bg-gray-50" data-item-id="${item._id}">
            <td class="px-6 py-4">
                <input type="checkbox" name="item_select" value="${item._id}" class="rounded text-primary focus:ring-primary">
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
                <div class="flex items-center">
                    <img src="${item.images[0] || '/static/img/default-dish.png'}" 
                         alt="${item.name}" 
                         class="w-12 h-12 rounded-lg object-cover">
                    <div class="ml-4">
                        <div class="text-sm font-medium text-gray-900">${item.name}</div>
                        <div class="text-sm text-gray-500">${item.description}</div>
                    </div>
                </div>
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
                <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-gray-100 text-gray-800">
                    ${item.category}
                </span>
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
                <span class="text-sm text-gray-900">$${item.price.toFixed(2)}</span>
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
                <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full 
                           ${item.active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}">
                    ${item.active ? 'Active' : 'Inactive'}
                </span>
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
                <span class="text-sm text-gray-900">${item.orders_count}</span>
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                <button onclick="editItem('${item._id}')" class="text-blue-600 hover:text-blue-900 mr-3">
                    <i class="fas fa-edit"></i>
                </button>
                <button onclick="deleteItem('${item._id}')" class="text-red-600 hover:text-red-900">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        </tr>
    `).join('');
}

function clearImagePreviews() {
    const container = document.getElementById('imagePreviewContainer');
    const preview = document.getElementById('previewImage');
    if (container) container.innerHTML = '';
    if (preview) preview.style.backgroundImage = '';
}

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
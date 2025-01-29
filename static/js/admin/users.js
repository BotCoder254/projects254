// User Management JavaScript

// Initialize socket connection
let currentUserId = null;
let socket = io();

// Socket.IO event listeners
socket.on('user_update', function(data) {
    if (data.stats) {
        document.getElementById('total-users').textContent = data.stats.total_users;
        document.getElementById('active-users').textContent = data.stats.active_users;
        document.getElementById('new-users-today').textContent = data.stats.new_users_today;
    }
    
    if (data.user) {
        const userRow = document.querySelector(`tr[data-user-id="${data.user._id}"]`);
        if (userRow) {
            updateUserRow(userRow, data.user);
        }
    }
});

// Define utility functions
function showAlert(message, type = 'info') {
    alert(message); // Simple alert for now
}

// Core functions
function editUser(userId) {
    currentUserId = userId;
    
    fetch(`/api/admin/users/${userId}`)
        .then(response => response.json())
        .then(user => {
            document.getElementById('editName').value = user.name;
            document.getElementById('editEmail').value = user.email;
            document.getElementById('editRole').value = user.role;
            document.getElementById('editStatus').value = user.status;
            
            const modal = document.getElementById('editUserModal');
            modal.classList.remove('hidden');
            modal.classList.add('flex');
        })
        .catch(error => {
            showAlert('Error loading user details');
            console.error('Error:', error);
        });
}

function deleteUser(userId) {
    currentUserId = userId;
    document.getElementById('deleteConfirmModal').classList.remove('hidden');
    document.getElementById('deleteConfirmModal').classList.add('flex');
}

function confirmDelete() {
    if (!currentUserId) return;
    
    fetch(`/api/admin/users/${currentUserId}`, {
        method: 'DELETE'
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showAlert('Successfully deleted user');
            closeDeleteModal();
            location.reload();
        } else {
            showAlert(data.error || 'An error occurred');
        }
    })
    .catch(error => {
        showAlert('Error deleting user');
        console.error('Error:', error);
    });
}

function closeEditModal() {
    const modal = document.getElementById('editUserModal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
}

function closeDeleteModal() {
    const modal = document.getElementById('deleteConfirmModal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
}

function updateUserRow(row, user) {
    row.innerHTML = `
        <td class="px-6 py-4">
            <input type="checkbox" name="user_select" value="${user._id}" class="rounded text-primary focus:ring-primary">
        </td>
        <td class="px-6 py-4 whitespace-nowrap">
            <div class="flex items-center">
                <img src="${user.avatar_url || '/static/img/default-avatar.png'}" 
                     alt="${user.name}" 
                     class="w-10 h-10 rounded-full">
                <div class="ml-4">
                    <div class="text-sm font-medium text-gray-900">${user.name}</div>
                    <div class="text-sm text-gray-500">${user.email}</div>
                </div>
            </div>
        </td>
        <td class="px-6 py-4 whitespace-nowrap">
            <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full 
                       ${user.status === 'active' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}">
                ${user.status.charAt(0).toUpperCase() + user.status.slice(1)}
            </span>
        </td>
        <td class="px-6 py-4 whitespace-nowrap">
            <span class="text-sm text-gray-900">${user.role.charAt(0).toUpperCase() + user.role.slice(1)}</span>
        </td>
        <td class="px-6 py-4 whitespace-nowrap">
            <span class="text-sm text-gray-900">${user.total_orders}</span>
        </td>
        <td class="px-6 py-4 whitespace-nowrap">
            <span class="text-sm text-gray-900">$${user.total_spent ? user.total_spent.toFixed(2) : '0.00'}</span>
        </td>
        <td class="px-6 py-4 whitespace-nowrap">
            <span class="text-sm text-gray-500">${user.last_activity ? new Date(user.last_activity).toLocaleString() : 'Never'}</span>
        </td>
        <td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
            <button onclick="editUser('${user._id}')" class="text-blue-600 hover:text-blue-900 mr-3">
                <i class="fas fa-edit"></i>
            </button>
            <button onclick="deleteUser('${user._id}')" class="text-red-600 hover:text-red-900">
                <i class="fas fa-trash"></i>
            </button>
        </td>
    `;
}

function bulkAction(action) {
    const selectedUsers = Array.from(document.querySelectorAll('input[name="user_select"]:checked'))
        .map(checkbox => checkbox.value);
    
    if (selectedUsers.length === 0) {
        showAlert('Please select users to perform this action');
        return;
    }
    
    if (action === 'delete' && !confirm('Are you sure you want to delete the selected users?')) {
        return;
    }
    
    fetch('/api/admin/users/bulk-action', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            user_ids: selectedUsers,
            action: action
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showAlert(`Successfully ${action}d selected users`);
            location.reload();
        } else {
            showAlert(data.error || 'An error occurred');
        }
    })
    .catch(error => {
        showAlert('An error occurred while performing the action');
        console.error('Error:', error);
    });
}

function filterUsers() {
    const query = document.getElementById('userSearch').value;
    const filter = document.getElementById('userFilter').value;
    
    fetch(`/api/admin/users/search?q=${query}&filter=${filter}`)
        .then(response => response.json())
        .then(data => {
            updateUsersTable(data);
        })
        .catch(error => {
            showAlert('An error occurred while filtering');
            console.error('Error:', error);
        });
}

function updateUsersTable(users) {
    const tbody = document.querySelector('tbody');
    if (!tbody) return;
    
    tbody.innerHTML = users.map(user => `
        <tr class="hover:bg-gray-50" data-user-id="${user._id}">
            <td class="px-6 py-4">
                <input type="checkbox" name="user_select" value="${user._id}" class="rounded text-primary focus:ring-primary">
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
                <div class="flex items-center">
                    <img src="${user.avatar_url || '/static/img/default-avatar.png'}" 
                         alt="${user.name}" 
                         class="w-10 h-10 rounded-full">
                    <div class="ml-4">
                        <div class="text-sm font-medium text-gray-900">${user.name}</div>
                        <div class="text-sm text-gray-500">${user.email}</div>
                    </div>
                </div>
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
                <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full 
                           ${user.status === 'active' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}">
                    ${user.status.charAt(0).toUpperCase() + user.status.slice(1)}
                </span>
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
                <span class="text-sm text-gray-900">${user.role.charAt(0).toUpperCase() + user.role.slice(1)}</span>
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
                <span class="text-sm text-gray-900">${user.total_orders}</span>
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
                <span class="text-sm text-gray-900">$${user.total_spent ? user.total_spent.toFixed(2) : '0.00'}</span>
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
                <span class="text-sm text-gray-500">${user.last_activity ? new Date(user.last_activity).toLocaleString() : 'Never'}</span>
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                <button onclick="editUser('${user._id}')" class="text-blue-600 hover:text-blue-900 mr-3">
                    <i class="fas fa-edit"></i>
                </button>
                <button onclick="deleteUser('${user._id}')" class="text-red-600 hover:text-red-900">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        </tr>
    `).join('');
}

// Initialize form submission handler
document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('editUserForm');
    if (form) {
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const formData = {
                name: document.getElementById('editName').value.trim(),
                email: document.getElementById('editEmail').value.trim(),
                role: document.getElementById('editRole').value,
                status: document.getElementById('editStatus').value
            };
            
            if (!formData.name) {
                showAlert('Please enter a name');
                return;
            }
            
            if (!formData.email) {
                showAlert('Please enter an email');
                return;
            }
            
            fetch(`/api/admin/users/${currentUserId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(formData)
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showAlert('Successfully updated user');
                    closeEditModal();
                    location.reload();
                } else {
                    showAlert(data.error || 'An error occurred');
                }
            })
            .catch(error => {
                showAlert('An error occurred while saving');
                console.error('Error:', error);
            });
        });
    }
    
    // Initialize search functionality
    const searchInput = document.getElementById('userSearch');
    if (searchInput) {
        searchInput.addEventListener('input', debounce(function() {
            filterUsers();
        }, 300));
    }
    
    // Initialize select all checkbox functionality
    const selectAll = document.getElementById('selectAll');
    if (selectAll) {
        selectAll.addEventListener('change', function(e) {
            const checkboxes = document.querySelectorAll('input[name="user_select"]');
            checkboxes.forEach(checkbox => checkbox.checked = e.target.checked);
        });
    }
});

// Expose functions to global scope
window.editUser = editUser;
window.deleteUser = deleteUser;
window.confirmDelete = confirmDelete;
window.closeEditModal = closeEditModal;
window.closeDeleteModal = closeDeleteModal;
window.bulkAction = bulkAction;
window.filterUsers = filterUsers;

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
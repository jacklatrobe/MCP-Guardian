// MCP Guardian Admin UI JavaScript

// Fetch helper - browser handles HTTP Basic Auth automatically
async function fetchWithAuth(url, options = {}) {
    // Browser will automatically include HTTP Basic Auth credentials
    // No need to manage tokens in JavaScript
    const response = await fetch(url, {
        ...options,
        credentials: 'include' // Include credentials for CORS if needed
    });
    
    // If unauthorized, browser will show login dialog again
    if (response.status === 401) {
        alert('Authentication required. Please log in.');
    }
    
    return response;
}

// Load services list
async function loadServices() {
    try {
        const response = await fetchWithAuth('/api/admin/services');
        const services = await response.json();
        
        if (services.length === 0) {
            document.getElementById('servicesContainer').innerHTML = 
                '<p>No services configured. Click "Add Service" to create one.</p>';
            return;
        }
        
        const servicesHtml = `
            <table>
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Upstream URL</th>
                        <th>Status</th>
                        <th>Check Freq</th>
                        <th>Latest Snapshot</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${services.map(service => `
                        <tr>
                            <td><strong>${service.name}</strong></td>
                            <td><code>${truncateUrl(service.upstream_url)}</code></td>
                            <td>
                                <span class="badge ${service.enabled ? 'badge-success' : 'badge-warning'}">
                                    ${service.enabled ? 'Enabled' : 'Disabled'}
                                </span>
                            </td>
                            <td>${service.check_frequency_minutes} min</td>
                            <td>
                                ${service.latest_snapshot_status ? 
                                    `<span class="badge badge-${getStatusColor(service.latest_snapshot_status)}">${service.latest_snapshot_status}</span>` :
                                    '<span class="badge badge-secondary">None</span>'
                                }
                            </td>
                            <td>
                                <button class="btn btn-primary" onclick="viewService('${service.name}')">View</button>
                                <button class="btn btn-danger" onclick="deleteService('${service.name}')">Delete</button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
        
        document.getElementById('servicesContainer').innerHTML = servicesHtml;
    } catch (error) {
        document.getElementById('servicesContainer').innerHTML = 
            `<p class="error">Error loading services: ${error.message}</p>`;
    }
}

function truncateUrl(url, maxLength = 50) {
    if (url.length <= maxLength) return url;
    return url.substring(0, maxLength - 3) + '...';
}

function getStatusColor(status) {
    switch (status) {
        case 'user_approved': return 'success';
        case 'system_approved': return 'info';
        case 'unapproved': return 'warning';
        default: return 'secondary';
    }
}

function viewService(name) {
    window.location.href = `/ADMIN/service/${name}`;
}

async function deleteService(name) {
    if (!confirm(`Delete service "${name}" and all its snapshots? This cannot be undone!`)) {
        return;
    }
    
    try {
        const response = await fetchWithAuth(`/api/admin/services/${name}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            await loadServices();
        } else {
            const error = await response.json();
            alert(`Error: ${error.detail}`);
        }
    } catch (error) {
        alert(`Error: ${error.message}`);
    }
}

// Modal management
function openModal() {
    document.getElementById('serviceModal').style.display = 'block';
    document.getElementById('serviceForm').reset();
    document.getElementById('formError').textContent = '';
    document.getElementById('formSuccess').textContent = '';
}

function closeModal() {
    document.getElementById('serviceModal').style.display = 'none';
}

// Handle service form submission
async function handleServiceSubmit(event) {
    event.preventDefault();
    
    // Disable submit button to prevent double-submission
    const submitBtn = event.target.querySelector('button[type="submit"]');
    if (submitBtn.disabled) return; // Already submitting
    submitBtn.disabled = true;
    submitBtn.textContent = 'Creating...';
    
    const formData = new FormData(event.target);
    const data = {
        name: formData.get('name'),
        upstream_url: formData.get('upstream_url'),
        check_frequency_minutes: parseInt(formData.get('check_frequency_minutes')),
        enabled: formData.get('enabled') === 'on'
    };
    
    const errorDiv = document.getElementById('formError');
    const successDiv = document.getElementById('formSuccess');
    errorDiv.textContent = '';
    successDiv.textContent = '';
    
    try {
        const response = await fetchWithAuth('/api/admin/services', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });
        
        if (response.ok) {
            successDiv.textContent = 'Service created successfully!';
            setTimeout(() => {
                closeModal();
                loadServices();
            }, 1500);
        } else {
            const error = await response.json();
            errorDiv.textContent = `Error: ${error.detail}`;
            // Re-enable button on error
            submitBtn.disabled = false;
            submitBtn.textContent = 'Create Service';
        }
    } catch (error) {
        errorDiv.textContent = `Error: ${error.message}`;
        // Re-enable button on error
        submitBtn.disabled = false;
        submitBtn.textContent = 'Create Service';
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    // Only load services on the main admin page
    if (document.getElementById('servicesContainer')) {
        loadServices();
        
        // Set up event listeners
        const addBtn = document.getElementById('addServiceBtn');
        if (addBtn) {
            addBtn.addEventListener('click', openModal);
        }
        
        const refreshBtn = document.getElementById('refreshBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', loadServices);
        }
        
        const closeBtn = document.querySelector('.close');
        if (closeBtn) {
            closeBtn.addEventListener('click', closeModal);
        }
        
        const serviceForm = document.getElementById('serviceForm');
        if (serviceForm) {
            serviceForm.addEventListener('submit', handleServiceSubmit);
        }
        
        // Close modal when clicking outside
        window.addEventListener('click', (event) => {
            const modal = document.getElementById('serviceModal');
            if (event.target === modal) {
                closeModal();
            }
        });
    }
});

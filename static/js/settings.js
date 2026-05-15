document.addEventListener('DOMContentLoaded', function() {
    const editBtn = document.getElementById('editProfileBtn');
    const modalEl = document.getElementById('editProfileModal');
    const editForm = document.getElementById('editProfileForm');
    const avatarInput = document.getElementById('avatarInput');
    const modalPreview = document.getElementById('modalAvatarPreview');
    const modalIcon = document.getElementById('modalAvatarIcon');
    const saveBtn = document.getElementById('saveProfileBtn');
    const toastEl = document.getElementById('settingsToast');
    
    let modal = null;
    if (modalEl) {
        modal = new bootstrap.Modal(modalEl);
    }

    // Open Modal
    if (editBtn) {
        editBtn.addEventListener('click', () => {
            modal.show();
        });
    }

    // Image Preview Logic
    if (avatarInput) {
        avatarInput.addEventListener('change', function() {
            const file = this.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = function(e) {
                    if (modalPreview) {
                        modalPreview.src = e.target.result;
                        modalPreview.style.display = 'block';
                    }
                    if (modalIcon) {
                        modalIcon.style.display = 'none';
                    }
                };
                reader.readAsDataURL(file);
            }
        });
    }

    // AJAX Profile Update
    if (editForm) {
        editForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const formData = new FormData(this);
            const spinner = saveBtn.querySelector('.spinner-border');
            
            // UI Loading State
            saveBtn.disabled = true;
            spinner.classList.remove('d-none');
            
            try {
                const response = await fetch('/update_profile', {
                    method: 'POST',
                    body: formData
                });
                
                const data = await response.json();
                
                if (data.success) {
                    // Update UI elements instantly
                    const displayUsername = document.getElementById('displayUsername');
                    const navbarUsername = document.querySelector('.profile-name');
                    const currentAvatarImg = document.getElementById('currentAvatarImg');
                    const navbarAvatars = document.querySelectorAll('.profile-avatar img');
                    
                    if (displayUsername) displayUsername.textContent = data.username;
                    if (navbarUsername) navbarUsername.textContent = data.username;
                    
                    if (data.avatar) {
                        const avatarUrl = `/static/uploads/profile/${data.avatar}`;
                        // Update settings card avatar
                        if (currentAvatarImg) {
                            currentAvatarImg.src = avatarUrl;
                        } else {
                            // If it was an icon, replace with img
                            const container = document.querySelector('.settings-card .profile-avatar');
                            if (container) container.innerHTML = `<img src="${avatarUrl}" id="currentAvatarImg" alt="Avatar" style="width: 100%; height: 100%; border-radius: 50%; object-fit: cover;">`;
                        }
                        
                        // Update all navbar avatars
                        navbarAvatars.forEach(img => {
                            img.src = avatarUrl;
                        });
                        
                        // Handle navbar if it was an icon
                        const navContainers = document.querySelectorAll('.navbar .profile-avatar');
                        navContainers.forEach(container => {
                           if (!container.querySelector('img')) {
                               container.innerHTML = `<img src="${avatarUrl}" alt="Avatar" style="width: 100%; height: 100%; border-radius: 50%; object-fit: cover;">`;
                           }
                        });
                    }
                    
                    // Show success toast
                    const toast = new bootstrap.Toast(toastEl);
                    toast.show();
                    
                    // Close modal
                    setTimeout(() => {
                        modal.hide();
                    }, 500);
                } else {
                    alert('Error: ' + data.error);
                }
            } catch (error) {
                console.error('Update failed:', error);
                alert('An unexpected error occurred. Please try again.');
            } finally {
                saveBtn.disabled = false;
                spinner.classList.add('d-none');
            }
        });
    }
});

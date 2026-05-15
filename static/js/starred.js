document.addEventListener('DOMContentLoaded', function() {
    const starButtons = document.querySelectorAll('.star-btn');
    
    starButtons.forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            
            const fileId = this.dataset.fileId;
            const icon = this.querySelector('i');
            
            fetch(`/toggle_star/${fileId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    if (data.is_starred) {
                        icon.classList.remove('bi-star');
                        icon.classList.add('bi-star-fill', 'text-warning', 'glowing-star');
                        this.title = "Unstar";
                    } else {
                        icon.classList.remove('bi-star-fill', 'text-warning', 'glowing-star');
                        icon.classList.add('bi-star');
                        this.title = "Star";
                        
                        // If we are on the starred page, remove the card
                        if (window.location.pathname === '/starred') {
                            const card = this.closest('.file-card-col');
                            if (card) {
                                card.style.opacity = '0';
                                card.style.transform = 'scale(0.8)';
                                setTimeout(() => {
                                    card.remove();
                                    // If no cards left, show empty state (optional)
                                    if (document.querySelectorAll('.file-card-col').length === 0) {
                                        location.reload();
                                    }
                                }, 300);
                            }
                        }
                    }
                }
            })
            .catch(error => {
                // Silently handle or use a more user-friendly notification in production
            });
        });
    });
});

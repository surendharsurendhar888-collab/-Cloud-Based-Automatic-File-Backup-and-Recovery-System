/* ── Landing Page Interactivity ── */

document.addEventListener('DOMContentLoaded', () => {
    
    // ── Reveal Animations on Scroll ──
    const reveals = document.querySelectorAll('.reveal');
    
    const revealOnScroll = () => {
        const windowHeight = window.innerHeight;
        const revealPoint = 150;
        
        reveals.forEach(reveal => {
            const revealTop = reveal.getBoundingClientRect().top;
            if (revealTop < windowHeight - revealPoint) {
                reveal.classList.add('active');
            }
        });
    };

    window.addEventListener('scroll', revealOnScroll);
    revealOnScroll(); // Initial check

    // ── Stats Counter Animation ──
    const stats = document.querySelectorAll('[data-count]');
    const countTime = 2000; // ms

    const animateCounters = () => {
        stats.forEach(stat => {
            const target = parseFloat(stat.getAttribute('data-count'));
            const isFloat = stat.getAttribute('data-count').includes('.');
            const step = target / (countTime / 16); // 60fps
            let current = 0;

            const updateCount = () => {
                current += step;
                if (current < target) {
                    stat.innerText = isFloat ? current.toFixed(1) : Math.floor(current);
                    requestAnimationFrame(updateCount);
                } else {
                    stat.innerText = target;
                }
            };
            
            // Only trigger when visible
            const observer = new IntersectionObserver((entries) => {
                if (entries[0].isIntersecting) {
                    updateCount();
                    observer.unobserve(stat);
                }
            });
            observer.observe(stat);
        });
    };

    animateCounters();

    // ── Navbar Scroll Effect ──
    const navbar = document.querySelector('.navbar-glass');
    window.addEventListener('scroll', () => {
        if (window.scrollY > 50) {
            navbar.style.padding = '0.6rem 0';
            navbar.style.boxShadow = '0 10px 30px rgba(0,0,0,0.3)';
        } else {
            navbar.style.padding = '1rem 0';
            navbar.style.boxShadow = 'none';
        }
    });

    // ── Smooth Scroll for Anchor Links ──
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                window.scrollTo({
                    top: target.offsetTop - 80,
                    behavior: 'smooth'
                });
            }
        });
    });
});

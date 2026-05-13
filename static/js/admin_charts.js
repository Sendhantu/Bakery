document.addEventListener('DOMContentLoaded', function() {
    // Shared chart options for styling consistency
    const commonOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: 'rgba(92, 61, 46, 0.9)',
                titleFont: { family: 'DM Sans', size: 13 },
                bodyFont: { family: 'DM Sans', size: 14, weight: 'bold' },
                padding: 10,
                cornerRadius: 8,
                displayColors: false
            }
        },
        scales: {
            x: {
                grid: { display: false, drawBorder: false },
                ticks: { font: { family: 'DM Sans', size: 12 }, color: '#666' }
            },
            y: {
                beginAtZero: true,
                grid: { color: 'rgba(0,0,0,0.05)', borderDash: [5, 5], drawBorder: false },
                ticks: { font: { family: 'DM Sans', size: 12 }, color: '#666', maxTicksLimit: 5 }
            }
        }
    };

    // Revenue Chart
    const revCanvas = document.getElementById('revenueChart');
    if (revCanvas) {
        const labels = JSON.parse(revCanvas.getAttribute('data-labels') || '[]');
        const data = JSON.parse(revCanvas.getAttribute('data-revenues') || '[]');
        
        const ctx = revCanvas.getContext('2d');
        const gradient = ctx.createLinearGradient(0, 0, 0, revCanvas.parentElement.offsetHeight);
        gradient.addColorStop(0, 'rgba(92, 61, 46, 0.5)'); // Brown start
        gradient.addColorStop(1, 'rgba(92, 61, 46, 0.0)'); // Transparent end

        new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Revenue (₹)',
                    data: data,
                    borderColor: '#5C3D2E',
                    backgroundColor: gradient,
                    borderWidth: 3,
                    pointBackgroundColor: '#fff',
                    pointBorderColor: '#5C3D2E',
                    pointBorderWidth: 2,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    fill: true,
                    tension: 0.4 // Smooth curves
                }]
            },
            options: Object.assign({}, commonOptions, {
                plugins: {
                    ...commonOptions.plugins,
                    tooltip: {
                        ...commonOptions.plugins.tooltip,
                        callbacks: {
                            label: function(context) {
                                return '₹ ' + context.parsed.y.toLocaleString();
                            }
                        }
                    }
                }
            })
        });
    }

    // Orders Chart
    const ordersCanvas = document.getElementById('ordersChart');
    if (ordersCanvas) {
        const labels = JSON.parse(ordersCanvas.getAttribute('data-labels') || '[]');
        const data = JSON.parse(ordersCanvas.getAttribute('data-orders') || '[]');
        
        new Chart(ordersCanvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Orders',
                    data: data,
                    backgroundColor: '#C8873A', // Gold/Accent color
                    borderRadius: 4,
                    barPercentage: 0.6
                }]
            },
            options: commonOptions
        });
    }
});

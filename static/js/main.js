/* Sweet Crumbs Bakery — Main JS */

document.addEventListener('DOMContentLoaded', () => {
  const formatCurrency = (value) => {
    const amount = Number(value || 0);
    return `₹${amount.toLocaleString('en-IN', {
      minimumFractionDigits: amount % 1 ? 2 : 0,
      maximumFractionDigits: 2,
    })}`;
  };

  const getCsrfToken = () => document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

  const withCsrfHeaders = (headers = {}) => {
    const token = getCsrfToken();
    return token ? {...headers, 'X-CSRFToken': token} : headers;
  };

  const applyCsrfToForms = (root = document) => {
    root.querySelectorAll('form[method="POST"], form[method="post"]').forEach((form) => {
      if (form.querySelector('input[name="csrf_token"]')) return;
      const token = getCsrfToken();
      if (!token) return;

      const input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'csrf_token';
      input.value = token;
      form.appendChild(input);
    });
  };

  const initImageFallbacks = (root = document) => {
    root.querySelectorAll('img[data-fallback-src]').forEach((img) => {
      if (img.dataset.fallbackBound === 'true') return;
      img.dataset.fallbackBound = 'true';
      img.addEventListener('error', () => {
        const fallback = img.dataset.fallbackSrc;
        if (!fallback || img.dataset.fallbackApplied === 'true') return;
        img.dataset.fallbackApplied = 'true';
        img.src = fallback;
      });
    });
  };

  const initConfirmDialogs = (root = document) => {
    root.querySelectorAll('[data-confirm]').forEach((el) => {
      if (el.dataset.confirmBound === 'true') return;
      el.dataset.confirmBound = 'true';
      el.addEventListener('click', (event) => {
        if (!window.confirm(el.dataset.confirm)) {
          event.preventDefault();
        }
      });
    });
  };

  const initToggleTargets = (root = document) => {
    root.querySelectorAll('[data-toggle-target]').forEach((button) => {
      if (button.dataset.toggleBound === 'true') return;
      button.dataset.toggleBound = 'true';
      button.addEventListener('click', () => {
        const target = document.querySelector(button.dataset.toggleTarget);
        if (!target) return;
        target.style.display = '';
        target.classList.remove('hidden');
        if (button.hasAttribute('data-toggle-hide-self')) {
          button.style.display = 'none';
        }
      });
    });

    root.querySelectorAll('[data-hide-target]').forEach((button) => {
      if (button.dataset.hideBound === 'true') return;
      button.dataset.hideBound = 'true';
      button.addEventListener('click', () => {
        const target = document.querySelector(button.dataset.hideTarget);
        if (!target) return;
        target.style.display = 'none';
        const trigger = document.querySelector(`[data-toggle-target="${button.dataset.hideTarget}"][data-toggle-hide-self]`);
        if (trigger) {
          trigger.style.display = '';
        }
      });
    });
  };

  const initMapToggles = (root = document) => {
    root.querySelectorAll('[data-map-toggle]').forEach((button) => {
      if (button.dataset.mapToggleBound === 'true') return;
      button.dataset.mapToggleBound = 'true';
      button.addEventListener('click', () => {
        const card = button.closest('[data-map-card], .address-map');
        const frame = card?.querySelector('[data-map-frame]');
        const iframe = frame?.querySelector('iframe');
        if (!frame || !iframe) return;

        const isHidden = frame.classList.contains('hidden');
        if (isHidden) {
          if (!iframe.src && iframe.dataset.mapSrc) {
            iframe.src = iframe.dataset.mapSrc;
          }
          frame.classList.remove('hidden');
          button.textContent = button.dataset.mapCloseLabel || 'Hide map';
        } else {
          frame.classList.add('hidden');
          button.textContent = button.dataset.mapOpenLabel || 'View map';
        }
      });
    });
  };

  const initPaymentOptions = () => {
    const options = document.querySelectorAll('[data-payment-option]');
    if (!options.length) return;

    const sync = () => {
      options.forEach((option) => {
        const input = option.querySelector('input[type="radio"]');
        option.classList.toggle('is-selected', Boolean(input?.checked));
      });
    };

    options.forEach((option) => {
      if (option.dataset.paymentBound === 'true') return;
      option.dataset.paymentBound = 'true';
      option.addEventListener('click', (event) => {
        if (event.target.matches('input[type="radio"]')) return;
        const input = option.querySelector('input[type="radio"]');
        if (!input) return;
        input.checked = true;
        input.dispatchEvent(new Event('change', {bubbles: true}));
      });
    });

    document.querySelectorAll('[data-payment-option] input[type="radio"]').forEach((input) => {
      input.addEventListener('change', sync);
    });
    sync();
  };

  const initCancelTimers = (root = document) => {
    root.querySelectorAll('[data-cancel-timer], #cancel-timer').forEach((cancelTimer) => {
      if (cancelTimer.dataset.cancelTimerBound === 'true') return;
      cancelTimer.dataset.cancelTimerBound = 'true';

      const targetTime = new Date(cancelTimer.dataset.placedAt);
      targetTime.setMinutes(targetTime.getMinutes() + 2);
      let intervalId = null;

      const tick = () => {
        if (!document.body.contains(cancelTimer)) {
          if (intervalId) window.clearInterval(intervalId);
          return;
        }

        const remaining = Math.max(0, Math.floor((targetTime - Date.now()) / 1000));
        if (remaining > 0) {
          const m = Math.floor(remaining / 60);
          const s = remaining % 60;
          cancelTimer.textContent = `${m}:${s.toString().padStart(2, '0')}`;
          return;
        }

        if (intervalId) window.clearInterval(intervalId);
        cancelTimer.closest('.cancel-window')?.remove();
        document.querySelector('.cancel-btn')?.remove();
      };

      tick();
      intervalId = window.setInterval(tick, 1000);
    });
  };

  const initializeUiBindings = (root = document) => {
    applyCsrfToForms(root);
    initImageFallbacks(root);
    initConfirmDialogs(root);
    initToggleTargets(root);
    initMapToggles(root);
    initCancelTimers(root);
    if (root === document) {
      initPaymentOptions();
    }
  };

  const body = document.body;
  const isAuthenticated = body.dataset.authenticated === 'true';
  const isAdminPage = body.dataset.pageRole === 'admin' || Boolean(document.querySelector('.admin-layout'));
  const adminScrollStorageKey = 'sweetcrumbs:admin-scroll-state';

  const saveAdminScrollState = () => {
    if (!isAdminPage) return;

    sessionStorage.setItem(adminScrollStorageKey, JSON.stringify({
      path: `${window.location.pathname}${window.location.search}`,
      scrollY: window.scrollY,
      timestamp: Date.now(),
    }));
  };

  const restoreAdminScrollState = () => {
    if (!isAdminPage) return;

    const savedState = sessionStorage.getItem(adminScrollStorageKey);
    if (!savedState) return;

    sessionStorage.removeItem(adminScrollStorageKey);

    try {
      const state = JSON.parse(savedState);
      const currentPath = `${window.location.pathname}${window.location.search}`;
      const isFresh = Date.now() - Number(state.timestamp || 0) < 5 * 60 * 1000;
      const savedScrollY = Number(state.scrollY || 0);

      if (!isFresh || state.path !== currentPath || savedScrollY <= 0) return;

      window.requestAnimationFrame(() => {
        window.scrollTo(0, savedScrollY);
        window.setTimeout(() => window.scrollTo(0, savedScrollY), 80);
      });
    } catch (error) {
      console.error('Unable to restore admin scroll position.', error);
    }
  };

  window.addEventListener('load', restoreAdminScrollState, { once: true });
  initializeUiBindings(document);

  if ('serviceWorker' in navigator && document.body.dataset.serviceWorkerUrl) {
    navigator.serviceWorker.register(document.body.dataset.serviceWorkerUrl).catch((error) => {
      console.error('Service worker registration failed.', error);
    });
  }

  const initConnectivityBanner = () => {
    if (!document.body.dataset.serviceWorkerUrl) return;
    let banner = document.getElementById('connectivity-banner');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'connectivity-banner';
      banner.className = 'flash-msg flash-warning';
      banner.style.display = 'none';
      document.querySelector('.flash-container')?.prepend(banner);
    }
    const setStatus = (online) => {
      if (!banner) return;
      banner.textContent = online
        ? 'Back online — syncing queued changes…'
        : 'You are offline. Changes will queue locally until connectivity returns.';
      banner.style.display = 'block';
      if (online) {
        fetch('/api/v2/sync/status', { credentials: 'same-origin' })
          .then((response) => response.json())
          .then((payload) => {
            if (payload.ok && payload.pending_actions > 0) {
              fetch('/api/v2/sync/flush', { method: 'POST', credentials: 'same-origin' });
            }
          })
          .catch(() => {});
        window.setTimeout(() => { banner.style.display = 'none'; }, 4000);
      }
    };
    window.addEventListener('online', () => setStatus(true));
    window.addEventListener('offline', () => setStatus(false));
    if (!navigator.onLine) setStatus(false);
  };
  initConnectivityBanner();

  // ─── Flash Messages ─────────────────────────────
  const flashes = document.querySelectorAll('.flash-msg');
  flashes.forEach(f => {
    setTimeout(() => {
      f.style.animation = 'slideIn 0.3s ease reverse';
      setTimeout(() => f.remove(), 300);
    }, 4500);
  });

  // ─── Hamburger Menu ──────────────────────────────
  const ham = document.querySelector('.hamburger');
  const navLinks = document.querySelector('.nav-links');
  const setNavOpen = (open) => {
    navLinks?.classList.toggle('open', open);
    ham?.classList.toggle('active', open);
    document.body.classList.toggle('nav-open', open);
  };
  ham?.addEventListener('click', () => {
    const isOpen = navLinks?.classList.contains('open');
    setNavOpen(!isOpen);
  });
  navLinks?.querySelectorAll('a').forEach((link) => {
    link.addEventListener('click', () => setNavOpen(false));
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') setNavOpen(false);
  });

  // ─── Admin Sidebar Toggle ────────────────────────
  const adminToggle = document.querySelector('.admin-menu-toggle');
  const adminSidebar = document.querySelector('.admin-sidebar');
  adminToggle?.addEventListener('click', () => {
    adminSidebar?.classList.toggle('open');
  });

  if (isAdminPage) {
    document.querySelectorAll('.admin-main form[method="POST"], .admin-main form[method="post"]').forEach((form) => {
      form.addEventListener('submit', () => {
        saveAdminScrollState();
      });
    });

    document.querySelectorAll('.admin-main a[href]').forEach((link) => {
      if (link.target === '_blank' || link.hasAttribute('download')) return;

      link.addEventListener('click', () => {
        const href = link.getAttribute('href');
        if (!href || href.startsWith('#')) return;

        try {
          const url = new URL(href, window.location.origin);
          const currentPath = `${window.location.pathname}${window.location.search}`;
          const targetPath = `${url.pathname}${url.search}`;
          if (url.origin === window.location.origin && targetPath === currentPath) {
            saveAdminScrollState();
          }
        } catch (error) {
          console.error('Unable to preserve admin scroll position.', error);
        }
      });
    });
  }

  const formatCountLabel = (count, singular, plural = `${singular}s`) => {
    const safeCount = Number(count || 0);
    return `${safeCount} ${safeCount === 1 ? singular : plural}`;
  };

  const updateCartPageSummary = (data, form) => {
    if (!data) return;

    setCartBadge(data.count || 0);

    if (data.empty) {
      window.location.reload();
      return;
    }

    const cartItem = form?.closest('[data-cart-item]');
    if (cartItem && data.item) {
      const quantityLabel = cartItem.querySelector('[data-cart-line-quantity]');
      const totalLabel = cartItem.querySelector('[data-cart-line-total]');
      if (quantityLabel) quantityLabel.textContent = `Quantity selected: ${data.item.quantity}`;
      if (totalLabel) totalLabel.textContent = formatCurrency(data.item.line_total);
    }

    const lineCount = Number(data.line_count || 0);
    const totalQuantity = Number(data.count || 0);

    const header = document.querySelector('#cart-header-count');
    if (header) {
      header.textContent = `${formatCountLabel(totalQuantity, 'item')} across ${formatCountLabel(lineCount, 'product')}`;
    }

    const productsEl = document.querySelector('#cart-summary-products');
    const quantityEl = document.querySelector('#cart-summary-quantity');
    const planningQtyEl = document.querySelector('#cart-planning-quantity');
    const subtotalEl = document.querySelector('#cart-summary-subtotal');
    const deliveryEl = document.querySelector('#cart-summary-delivery');
    const totalEl = document.querySelector('#cart-summary-total');
    const freeDeliveryNote = document.querySelector('#cart-free-delivery-note');

    if (productsEl) productsEl.textContent = lineCount;
    if (quantityEl) quantityEl.textContent = totalQuantity;
    if (planningQtyEl) planningQtyEl.textContent = totalQuantity;
    if (subtotalEl) subtotalEl.textContent = formatCurrency(data.subtotal || 0);
    if (deliveryEl) {
      deliveryEl.innerHTML = Number(data.delivery_charge || 0) === 0
        ? '<span style="color:var(--sage)">FREE</span>'
        : formatCurrency(data.delivery_charge || 0);
    }
    if (totalEl) totalEl.textContent = formatCurrency(data.grand_total || 0);

    if (freeDeliveryNote) {
      const remainingForFreeDelivery = Math.max(0, Number(data.delivery_threshold || 500) - Number(data.subtotal || 0));
      if (remainingForFreeDelivery <= 0) {
        freeDeliveryNote.style.display = 'none';
      } else {
        freeDeliveryNote.style.display = 'block';
        freeDeliveryNote.innerHTML = `Add ${formatCurrency(remainingForFreeDelivery)} more for <strong style="color:var(--sage)">FREE delivery</strong> 🎁`;
      }
    }
  };

  const submitCartQuantityForm = async (form) => {
    if (!form || form.dataset.submitting === 'true') return;

    const qtyControl = form.querySelector('.qty-control');
    form.dataset.submitting = 'true';
    qtyControl?.classList.add('is-loading');

    try {
      const response = await fetch(form.action, {
        method: 'POST',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'Accept': 'application/json',
          ...withCsrfHeaders(),
        },
        body: new FormData(form),
      });

      if (response.redirected) {
        window.location.href = response.url;
        return;
      }

      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(data.message || 'Unable to update cart quantity.');
      }

      updateCartPageSummary(data, form);
    } catch (error) {
      console.error(error);
      form.submit();
    } finally {
      delete form.dataset.submitting;
      qtyControl?.classList.remove('is-loading');
    }
  };

  // ─── Quantity Controls ───────────────────────────
  document.querySelectorAll('.qty-control').forEach((ctrl) => {
    const input = ctrl.querySelector('.qty-input');
    const form = ctrl.closest('form[data-cart-quantity-form]');

    const applyQuantityDelta = (delta) => {
      const value = parseInt(input.value, 10) || 1;
      const min = parseInt(input.min, 10) || 1;
      const max = parseInt(input.max, 10) || 99;
      const nextValue = Math.min(max, Math.max(min, value + delta));
      if (nextValue === value) return;

      input.value = nextValue;
      input.dispatchEvent(new Event('change', { bubbles: true }));

      if (form) {
        submitCartQuantityForm(form);
      }
    };

    ctrl.querySelector('.qty-minus')?.addEventListener('click', () => applyQuantityDelta(-1));
    ctrl.querySelector('.qty-plus')?.addEventListener('click', () => applyQuantityDelta(1));
  });

  document.querySelectorAll('form[data-cart-quantity-form]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      submitCartQuantityForm(form);
    });
  });

  // ─── Product Variant Selector ────────────────────
  const variantBtns = document.querySelectorAll('.variant-btn');
  variantBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const group = btn.closest('.variant-group');
      group.querySelectorAll('.variant-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      const price = btn.dataset.price;
      const stock = btn.dataset.stock;
      const variantId = btn.dataset.variantId;

      // Update price display
      const priceDisplay = document.querySelector('.current-price');
      if (priceDisplay && price) priceDisplay.textContent = `₹${parseFloat(price).toLocaleString('en-IN')}`;

      // Update stock badge
      const stockBadge = document.querySelector('.live-stock-badge');
      if (stockBadge) {
        if (stock == 0) {
          stockBadge.className = 'badge badge-red live-stock-badge';
          stockBadge.textContent = 'Out of Stock';
        } else if (stock <= 5) {
          stockBadge.className = 'badge badge-orange live-stock-badge';
          stockBadge.textContent = `Only ${stock} left!`;
        } else {
          stockBadge.className = 'badge badge-green live-stock-badge';
          stockBadge.textContent = 'In Stock';
        }
      }

      // Update hidden variant input
      const variantInput = document.querySelector('#variant_id');
      if (variantInput && variantId) variantInput.value = variantId;

      // Qty max
      const qtyInput = document.querySelector('.qty-input');
      if (qtyInput) qtyInput.max = stock;
    });
  });

  // ─── Coupon Validation ───────────────────────────
  const couponBtn = document.querySelector('#apply-coupon-btn');
  const loyaltyBtn = document.querySelector('#preview-loyalty-btn');
  const checkoutTotalEl = document.querySelector('#order-total');
  const pricingState = {
    couponDiscount: 0,
    loyaltyDiscount: 0,
    fulfillmentType: document.querySelector('input[name="fulfillment_type"]:checked')?.value || 'DELIVERY',
  };

  const renderCheckoutPricing = () => {
    if (!checkoutTotalEl) return;

    const baseTotal = parseFloat(checkoutTotalEl.dataset.baseTotal || 0);
    const deliveryCharge = parseFloat(checkoutTotalEl.dataset.deliveryCharge || 0);
    const effectiveBaseTotal = baseTotal - (pricingState.fulfillmentType === 'PICKUP' ? deliveryCharge : 0);
    const total = Math.max(0, effectiveBaseTotal - pricingState.couponDiscount - pricingState.loyaltyDiscount);

    const couponRow = document.querySelector('#coupon-discount-row');
    const couponVal = document.querySelector('#coupon-discount-val');
    if (couponRow && couponVal) {
      couponRow.style.display = pricingState.couponDiscount > 0 ? 'flex' : 'none';
      couponVal.textContent = `−${formatCurrency(pricingState.couponDiscount)}`;
    }

    const loyaltyRow = document.querySelector('#loyalty-discount-row');
    const loyaltyVal = document.querySelector('#loyalty-discount-val');
    if (loyaltyRow && loyaltyVal) {
      loyaltyRow.style.display = pricingState.loyaltyDiscount > 0 ? 'flex' : 'none';
      loyaltyVal.textContent = `−${formatCurrency(pricingState.loyaltyDiscount)}`;
    }

    const fulfillmentChargeLabel = document.querySelector('#checkout-fulfillment-charge-label');
    const fulfillmentChargeValue = document.querySelector('#checkout-fulfillment-charge-value');
    const fulfillmentChargeNote = document.querySelector('#checkout-fulfillment-charge-note');
    if (fulfillmentChargeLabel && fulfillmentChargeValue && fulfillmentChargeNote) {
      if (!fulfillmentChargeNote.dataset.deliveryNote) {
        fulfillmentChargeNote.dataset.deliveryNote = fulfillmentChargeNote.textContent.trim();
      }
      if (pricingState.fulfillmentType === 'PICKUP') {
        fulfillmentChargeLabel.textContent = 'Pickup';
        fulfillmentChargeValue.innerHTML = '<span style="color:var(--sage)">FREE</span>';
        fulfillmentChargeNote.textContent = 'Pickup orders do not include a delivery charge.';
      } else {
        fulfillmentChargeLabel.textContent = 'Delivery';
        fulfillmentChargeValue.innerHTML = deliveryCharge > 0
          ? formatCurrency(deliveryCharge)
          : '<span style="color:var(--sage)">FREE</span>';
        fulfillmentChargeNote.textContent = fulfillmentChargeNote.dataset.deliveryNote;
      }
    }

    checkoutTotalEl.textContent = formatCurrency(total);
  };

  couponBtn?.addEventListener('click', async () => {
    const code = document.querySelector('#coupon_code')?.value?.trim();
    const subtotal = parseFloat(document.querySelector('#subtotal-value')?.dataset?.value || 0);
    const msgEl = document.querySelector('#coupon-msg');

    if (!code) {
      pricingState.couponDiscount = 0;
      if (msgEl) msgEl.textContent = '';
      renderCheckoutPricing();
      return;
    }

    couponBtn.innerHTML = '<span class="spinner"></span>';
    couponBtn.disabled = true;

    try {
      const res = await fetch('/api/validate-coupon', {
        method: 'POST',
        headers: withCsrfHeaders({'Content-Type': 'application/json'}),
        body: JSON.stringify({code, subtotal})
      });
      const data = await res.json();

      if (data.valid) {
        pricingState.couponDiscount = Number(data.discount || 0);
        if (msgEl) {
          msgEl.textContent = data.message;
          msgEl.className = 'text-sm badge badge-green mt-1';
        }
      } else {
        pricingState.couponDiscount = 0;
        if (msgEl) {
          msgEl.textContent = data.message;
          msgEl.className = 'text-sm badge badge-red mt-1';
        }
      }
      renderCheckoutPricing();
    } catch (e) {
      console.error(e);
    } finally {
      couponBtn.innerHTML = 'Apply';
      couponBtn.disabled = false;
    }
  });

  const previewLoyalty = async () => {
    const pointsInput = document.querySelector('#checkout-loyalty-input');
    const msgEl = document.querySelector('#loyalty-msg');
    const summaryEl = document.querySelector('#loyalty-points-summary');
    const subtotal = parseFloat(document.querySelector('#subtotal-value')?.dataset?.value || 0);
    const points = parseInt(pointsInput?.value || '0', 10) || 0;

    if (!points) {
      pricingState.loyaltyDiscount = 0;
      if (msgEl) msgEl.textContent = '';
      if (summaryEl) summaryEl.textContent = '';
      renderCheckoutPricing();
      return;
    }

    if (loyaltyBtn) {
      loyaltyBtn.disabled = true;
      loyaltyBtn.innerHTML = '<span class="spinner"></span>';
    }

    try {
      const res = await fetch('/api/loyalty/validate-redeem', {
        method: 'POST',
        headers: withCsrfHeaders({'Content-Type': 'application/json'}),
        body: JSON.stringify({points, subtotal}),
      });
      const data = await res.json();
      if (data.valid) {
        pricingState.loyaltyDiscount = Number(data.discount || 0);
        if (msgEl) {
          msgEl.textContent = data.message;
          msgEl.className = `text-sm badge ${data.capped ? 'badge-orange' : 'badge-green'} mt-1`;
        }
        if (summaryEl) {
          summaryEl.textContent = data.capped
            ? `Preview capped to ${data.points_applied} points for this order.`
            : `Previewing ${data.points_applied} points on this order.`;
        }
      } else {
        pricingState.loyaltyDiscount = 0;
        if (msgEl) {
          msgEl.textContent = data.message;
          msgEl.className = 'text-sm badge badge-red mt-1';
        }
        if (summaryEl) summaryEl.textContent = '';
      }
      renderCheckoutPricing();
    } catch (error) {
      console.error(error);
    } finally {
      if (loyaltyBtn) {
        loyaltyBtn.disabled = false;
        loyaltyBtn.innerHTML = 'Preview';
      }
    }
  };

  loyaltyBtn?.addEventListener('click', previewLoyalty);
  document.querySelector('#checkout-loyalty-input')?.addEventListener('change', previewLoyalty);

  // ─── Search Suggestions ──────────────────────────
  const searchInput = document.querySelector('.search-input');
  const suggestionsEl = document.querySelector('.search-suggestions');
  let searchTimeout;

  searchInput?.addEventListener('input', () => {
    clearTimeout(searchTimeout);
    const q = searchInput.value.trim();
    if (q.length < 2) { suggestionsEl && (suggestionsEl.innerHTML = ''); return; }

    searchTimeout = setTimeout(async () => {
      const res = await fetch(`/api/search/suggestions?q=${encodeURIComponent(q)}`);
      const data = await res.json();
      if (suggestionsEl) {
        suggestionsEl.innerHTML = data.map(p => `
          <a href="/product/${p.id}" class="suggestion-item">
            <span>${p.name}</span>
            <span class="text-caramel fw-600">₹${p.price}</span>
          </a>
        `).join('') || '<div class="suggestion-item text-muted">No results found</div>';
      }
    }, 300);
  });

  document.addEventListener('click', e => {
    if (!e.target.closest('.search-bar') && suggestionsEl) {
      suggestionsEl.innerHTML = '';
    }
  });

  // ─── Star Rating Input ───────────────────────────
  const stars = document.querySelectorAll('.star-input');
  stars.forEach(star => {
    star.addEventListener('mouseover', () => {
      const val = parseInt(star.dataset.value);
      stars.forEach((s, i) => {
        s.textContent = i < val ? '★' : '☆';
        s.style.color = i < val ? '#C8873A' : '#ccc';
      });
    });
    star.addEventListener('click', () => {
      const val = star.dataset.value;
      document.querySelector('#rating-input').value = val;
      stars.forEach((s, i) => {
        s.textContent = i < val ? '★' : '☆';
        s.style.color = i < val ? '#C8873A' : '#ccc';
        if (i < val) s.classList.add('selected');
      });
    });
  });

  document.querySelector('.star-rating-container')?.addEventListener('mouseleave', () => {
    const selected = parseInt(document.querySelector('#rating-input')?.value || 0);
    stars.forEach((s, i) => {
      s.textContent = i < selected ? '★' : '☆';
      s.style.color = i < selected ? '#C8873A' : '#ccc';
    });
  });

  if (stars.length) {
    const selected = parseInt(document.querySelector('#rating-input')?.value || 0);
    stars.forEach((s, i) => {
      s.textContent = i < selected ? '★' : '☆';
      s.style.color = i < selected ? '#C8873A' : '#ccc';
    });
  }

  // ─── Cart count from API ─────────────────────────
  const cartCountEl = document.querySelector('.cart-count');
  const setCartBadge = (count) => {
    if (!cartCountEl) return;
    cartCountEl.textContent = count;
    cartCountEl.classList.toggle('hidden', count <= 0);
  };

  if (cartCountEl) {
    fetch('/api/cart/count').then(r => r.json()).then(d => {
      setCartBadge(d.count);
    }).catch(() => {});
  }

  // ─── Mini Cart / AJAX Add to Cart ───────────────
  const miniCart = document.querySelector('#mini-cart');
  const miniCartAdded = document.querySelector('#mini-cart-added');
  const miniCartList = document.querySelector('#mini-cart-list');
  const miniCartCount = document.querySelector('#mini-cart-count');
  const miniCartSubtotal = document.querySelector('#mini-cart-subtotal');
  const miniCartCheckout = document.querySelector('#mini-cart-checkout');

  const renderMiniCartEntry = (item) => `
    <div class="mini-cart-entry">
      <img src="${item.image}" alt="${item.name}">
      <div>
        <div class="mini-cart-title">${item.name}</div>
        <div class="mini-cart-meta">${item.variant || 'Standard'} · Qty ${item.quantity}</div>
        <div class="mini-cart-meta">${formatCurrency(item.line_total)}</div>
      </div>
    </div>
  `;

  const openMiniCart = () => {
    if (!miniCart) return;
    miniCart.classList.add('open');
    miniCart.setAttribute('aria-hidden', 'false');
  };

  const closeMiniCart = () => {
    if (!miniCart) return;
    miniCart.classList.remove('open');
    miniCart.setAttribute('aria-hidden', 'true');
  };

  const renderMiniCart = (data) => {
    if (!miniCart) return;

    const addedItem = data.added_item || data.items?.[0];
    miniCartAdded.innerHTML = addedItem ? renderMiniCartEntry(addedItem) : '';
    miniCartList.innerHTML = (data.items || []).map(renderMiniCartEntry).join('');
    miniCartCount.textContent = data.count || 0;
    miniCartSubtotal.textContent = formatCurrency(data.subtotal || 0);
    if (miniCartCheckout && data.checkout_url) {
      miniCartCheckout.href = data.checkout_url;
    }
  };

  document.querySelectorAll('[data-mini-cart-close]').forEach((button) => {
    button.addEventListener('click', closeMiniCart);
  });

  document.querySelectorAll('form[action$="/cart/add"]').forEach((form) => {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const submitButton = form.querySelector('button[type="submit"], .btn');
      const originalLabel = submitButton?.innerHTML;
      if (submitButton) {
        submitButton.disabled = true;
        submitButton.innerHTML = '<span class="spinner"></span>';
      }

      try {
        const response = await fetch(form.action, {
          method: 'POST',
          headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json',
            ...withCsrfHeaders(),
          },
          body: new FormData(form),
        });

        if (response.redirected) {
          window.location.href = response.url;
          return;
        }

        const data = await response.json();
        if (!response.ok || !data.ok) {
          alert(data.message || 'Unable to add the product to cart.');
          return;
        }

        setCartBadge(data.count || 0);
        renderMiniCart(data);
        openMiniCart();
      } catch (error) {
        console.error(error);
      } finally {
        if (submitButton) {
          submitButton.disabled = false;
          submitButton.innerHTML = originalLabel;
        }
      }
    });
  });

  // ─── Image preview for admin ─────────────────────
  const imgInput = document.querySelector('#product-image-input');
  const imgPreview = document.querySelector('#image-preview');
  imgInput?.addEventListener('change', e => {
    const file = e.target.files[0];
    if (file && imgPreview) {
      const reader = new FileReader();
      reader.onload = ev => { imgPreview.src = ev.target.result; imgPreview.style.display = 'block'; };
      reader.readAsDataURL(file);
    }
  });

  // ─── Add Variant Row ─────────────────────────────
  document.querySelector('#add-variant-btn')?.addEventListener('click', () => {
    const container = document.querySelector('#variants-container');
    const row = document.createElement('div');
    row.className = 'variant-row flex gap-2 items-center mt-2';
    row.innerHTML = `
      <input type="hidden" name="variant_id[]" value="">
      <input class="form-control" type="text" name="variant_name[]" placeholder="e.g. 1 kg" required>
      <input class="form-control" type="number" name="variant_price[]" placeholder="Price" required>
      <input class="form-control" type="number" name="variant_stock[]" placeholder="Stock">
      <button type="button" class="btn btn-ghost text-muted remove-variant-btn" style="flex-shrink:0">✕</button>
    `;
    row.querySelector('.remove-variant-btn').addEventListener('click', () => row.remove());
    container?.appendChild(row);
  });

  document.querySelectorAll('.remove-variant-btn').forEach(btn => {
    btn.addEventListener('click', () => btn.closest('.variant-row')?.remove());
  });

  // ─── Add Recipe Material Row ────────────────────
  document.querySelector('#add-material-btn')?.addEventListener('click', () => {
    const container = document.querySelector('#materials-container');
    const firstRow = container?.querySelector('.material-row');
    if (!container || !firstRow) return;

    const row = firstRow.cloneNode(true);
    row.querySelectorAll('input').forEach(input => { input.value = ''; });
    row.querySelectorAll('select').forEach(select => { select.selectedIndex = 0; });
    row.querySelector('.remove-material-btn')?.addEventListener('click', () => row.remove());
    container.appendChild(row);
  });

  document.querySelectorAll('.remove-material-btn').forEach(btn => {
    btn.addEventListener('click', () => btn.closest('.material-row')?.remove());
  });

  // ─── Charts (Admin) ──────────────────────────────
  initCharts();

  // ─── Delivery date min ───────────────────────────
  const deliveryDate = document.querySelector('#delivery_date');
  const pickupDate = document.querySelector('#pickup_date');
  if (deliveryDate) {
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    deliveryDate.min = tomorrow.toISOString().split('T')[0];
  }
  if (pickupDate) {
    pickupDate.min = new Date().toISOString().split('T')[0];
  }

  const initCheckoutFulfillment = () => {
    const deliverySection = document.querySelector('#delivery-schedule-fields');
    const pickupSection = document.querySelector('#pickup-schedule-fields');
    const addressCard = document.querySelector('#checkout-address-card');
    const deliverySlot = document.querySelector('#delivery_time_slot');
    const pickupSlot = document.querySelector('#pickup_slot');
    const customPickupTime = document.querySelector('#custom_pickup_time');
    const pickupPhone = document.querySelector('#pickup_phone');

    const syncFulfillmentState = () => {
      const selectedValue = document.querySelector('input[name="fulfillment_type"]:checked')?.value || 'DELIVERY';
      pricingState.fulfillmentType = selectedValue;
      const isPickup = selectedValue === 'PICKUP';

      if (deliverySection) deliverySection.classList.toggle('hidden', isPickup);
      if (pickupSection) pickupSection.classList.toggle('hidden', !isPickup);
      if (addressCard) addressCard.classList.toggle('hidden', isPickup);

      if (deliveryDate) deliveryDate.required = !isPickup;
      if (deliverySlot) deliverySlot.required = !isPickup;
      if (pickupDate) pickupDate.required = isPickup;
      if (pickupPhone) pickupPhone.required = isPickup;

      if (isPickup) {
        deliveryDate?.removeAttribute('aria-required');
        deliverySlot?.removeAttribute('aria-required');
      }

      if (!isPickup) {
        pickupSlot && (pickupSlot.value = pickupSlot.value);
        customPickupTime && (customPickupTime.value = customPickupTime.value);
      }

      renderCheckoutPricing();
    };

    document.querySelectorAll('input[name="fulfillment_type"]').forEach((input) => {
      input.addEventListener('change', syncFulfillmentState);
    });
    syncFulfillmentState();
  };

  initCheckoutFulfillment();

  // ─── Checkout Saved Addresses ───────────────────
  const addressCards = document.querySelectorAll('.saved-address-card');
  const addressInputs = {
    label: document.querySelector('#checkout-address-label'),
    addressLine1: document.querySelector('#checkout-address-line1'),
    addressLine2: document.querySelector('#checkout-address-line2'),
    city: document.querySelector('#checkout-city'),
    pincode: document.querySelector('#checkout-pincode'),
    phone: document.querySelector('#checkout-phone'),
    latitude: document.querySelector('#checkout-latitude'),
    longitude: document.querySelector('#checkout-longitude'),
  };
  if (addressInputs.addressLine1 || addressCards.length) {
    const checkoutMapFrame = document.querySelector('#checkout-address-map-frame');
    const checkoutMapLink = document.querySelector('#checkout-address-map-link');
    const checkoutMapEmpty = document.querySelector('#checkout-address-map-empty');
    const checkoutMapToggle = document.querySelector('#checkout-address-map-toggle');
    const checkoutLocationStatus = document.querySelector('#checkout-location-status');
    const checkoutUseLocationButton = document.querySelector('#checkout-use-location');
    let suppressExactLocationReset = false;

    const buildAddressQuery = () => {
      const parts = [
        addressInputs.addressLine1?.value || '',
        addressInputs.addressLine2?.value || '',
        addressInputs.city?.value || '',
        addressInputs.pincode?.value || '',
      ].map((part) => part.trim()).filter(Boolean);
      return parts.join(', ');
    };

    const getExactLocation = () => {
      const rawLatitude = addressInputs.latitude?.value?.trim() || '';
      const rawLongitude = addressInputs.longitude?.value?.trim() || '';
      if (!rawLatitude || !rawLongitude) return null;

      const latitude = Number(rawLatitude);
      const longitude = Number(rawLongitude);
      if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
      if (latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) return null;

      return {
        latitude: Number(latitude.toFixed(7)),
        longitude: Number(longitude.toFixed(7)),
      };
    };

    const setLocationStatus = (message) => {
      if (checkoutLocationStatus) {
        checkoutLocationStatus.textContent = message;
      }
    };

    const fillAddressFromReverseGeocode = (location) => {
      if (!location) return;

      suppressExactLocationReset = true;
      if (addressInputs.addressLine1 && location.address_line1) {
        addressInputs.addressLine1.value = location.address_line1;
      }
      if (addressInputs.addressLine2 && location.address_line2) {
        addressInputs.addressLine2.value = location.address_line2;
      }
      if (addressInputs.city && location.city) {
        addressInputs.city.value = location.city;
      }
      if (addressInputs.pincode && location.pincode) {
        addressInputs.pincode.value = String(location.pincode).slice(0, 6);
      }
      suppressExactLocationReset = false;
    };

    const clearExactLocation = (message = 'Share your live location to place the map pin exactly on your address.') => {
      if (addressInputs.latitude) addressInputs.latitude.value = '';
      if (addressInputs.longitude) addressInputs.longitude.value = '';
      setLocationStatus(message);
    };

    const updateCheckoutAddressMap = () => {
      const query = buildAddressQuery();
      const exactLocation = getExactLocation();
      if (!checkoutMapFrame || !checkoutMapLink || !checkoutMapEmpty) return;

      if (!query && !exactLocation) {
        checkoutMapFrame.src = '';
        checkoutMapFrame.dataset.mapSrc = '';
        checkoutMapLink.href = '#';
        checkoutMapLink.classList.add('hidden');
        checkoutMapEmpty.classList.remove('hidden');
        checkoutMapFrame.closest('[data-map-frame]')?.classList.add('hidden');
        if (checkoutMapToggle) {
          checkoutMapToggle.disabled = true;
          checkoutMapToggle.textContent = checkoutMapToggle.dataset.mapOpenLabel || 'View map';
        }
        return;
      }

      const mapTarget = exactLocation
        ? `${exactLocation.latitude},${exactLocation.longitude}`
        : query;
      const encodedTarget = encodeURIComponent(mapTarget);
      const zoomLevel = exactLocation ? 17 : 15;

      checkoutMapFrame.dataset.mapSrc = `https://www.google.com/maps?q=${encodedTarget}&z=${zoomLevel}&output=embed`;
      if (!checkoutMapFrame.closest('[data-map-frame]')?.classList.contains('hidden')) {
        checkoutMapFrame.src = checkoutMapFrame.dataset.mapSrc;
      }
      checkoutMapLink.href = `https://www.google.com/maps/search/?api=1&query=${encodedTarget}`;
      checkoutMapLink.classList.remove('hidden');
      checkoutMapEmpty.classList.add('hidden');
      if (checkoutMapToggle) {
        checkoutMapToggle.disabled = false;
      }
      if (exactLocation) {
        setLocationStatus('Exact location captured. The map pin will open at the customer’s precise location.');
      } else {
        setLocationStatus('Map preview is based on the typed delivery address. Share live location for an exact pin.');
      }
    };

    const applyAddressCard = (card) => {
      if (!card) return;
      suppressExactLocationReset = true;
      if (addressInputs.label) addressInputs.label.value = card.dataset.label || '';
      if (addressInputs.addressLine1) addressInputs.addressLine1.value = card.dataset.addressLine1 || '';
      if (addressInputs.addressLine2) addressInputs.addressLine2.value = card.dataset.addressLine2 || '';
      if (addressInputs.city) addressInputs.city.value = card.dataset.city || '';
      if (addressInputs.pincode) addressInputs.pincode.value = card.dataset.pincode || '';
      if (addressInputs.phone) addressInputs.phone.value = card.dataset.phone || '';
      if (addressInputs.latitude) addressInputs.latitude.value = card.dataset.latitude || '';
      if (addressInputs.longitude) addressInputs.longitude.value = card.dataset.longitude || '';
      suppressExactLocationReset = false;
      updateCheckoutAddressMap();
    };

    const setSelectedAddressCard = (selectedCard) => {
      addressCards.forEach((card) => {
        card.classList.toggle('selected', card === selectedCard);
      });
      applyAddressCard(selectedCard);
    };

    addressCards.forEach((card) => {
      const radio = card.querySelector('input[type="radio"]');
      if (!radio) return;

      card.addEventListener('click', (event) => {
        if (event.target === radio) return;
        radio.checked = true;
        radio.dispatchEvent(new Event('change', { bubbles: true }));
      });

      radio.addEventListener('change', () => {
        if (radio.checked) {
          setSelectedAddressCard(card);
        }
      });

      if (radio.checked) {
        setSelectedAddressCard(card);
      }
    });

    [
      addressInputs.addressLine1,
      addressInputs.addressLine2,
      addressInputs.city,
      addressInputs.pincode,
    ].forEach((input) => {
      input?.addEventListener('input', () => {
        if (!suppressExactLocationReset) {
          clearExactLocation();
        }
        updateCheckoutAddressMap();
      });
      input?.addEventListener('change', () => {
        if (!suppressExactLocationReset) {
          clearExactLocation();
        }
        updateCheckoutAddressMap();
      });
    });

    [addressInputs.label, addressInputs.phone].forEach((input) => {
      input?.addEventListener('input', updateCheckoutAddressMap);
      input?.addEventListener('change', updateCheckoutAddressMap);
    });

    checkoutUseLocationButton?.addEventListener('click', () => {
      if (!navigator.geolocation) {
        setLocationStatus('Live location is not supported in this browser.');
        return;
      }

      const originalLabel = checkoutUseLocationButton.textContent;
      checkoutUseLocationButton.disabled = true;
      checkoutUseLocationButton.textContent = 'Locating...';
      setLocationStatus('Requesting your current location...');

      navigator.geolocation.getCurrentPosition(
        async (position) => {
          if (addressInputs.latitude) addressInputs.latitude.value = String(position.coords.latitude);
          if (addressInputs.longitude) addressInputs.longitude.value = String(position.coords.longitude);
          setLocationStatus('Exact map pin captured. Looking up the address...');

          try {
            const params = new URLSearchParams({
              lat: String(position.coords.latitude),
              lng: String(position.coords.longitude),
            });
            const response = await fetch(`/api/location/reverse-geocode?${params.toString()}`, {
              headers: {
                Accept: 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
              },
              cache: 'no-store',
            });
            const data = await response.json().catch(() => ({}));
            if (response.ok && data.ok) {
              fillAddressFromReverseGeocode(data.location);
              setLocationStatus(data.message || 'Exact location captured and address fields updated.');
            } else {
              setLocationStatus(data.message || 'Exact location captured. Please check the address fields manually.');
            }
          } catch (error) {
            console.error('Reverse geocoding failed.', error);
            setLocationStatus('Exact location captured. Please review the address fields before placing the order.');
          } finally {
            checkoutUseLocationButton.disabled = false;
            checkoutUseLocationButton.textContent = originalLabel;
          }
          updateCheckoutAddressMap();
        },
        (error) => {
          checkoutUseLocationButton.disabled = false;
          checkoutUseLocationButton.textContent = originalLabel;
          if (error.code === error.PERMISSION_DENIED) {
            setLocationStatus('Location access was denied. Allow location access to pin the exact delivery spot.');
          } else if (error.code === error.TIMEOUT) {
            setLocationStatus('Location lookup timed out. Please try again.');
          } else {
            setLocationStatus('Unable to fetch your live location right now.');
          }
        },
        {
          enableHighAccuracy: true,
          timeout: 10000,
          maximumAge: 0,
        },
      );
    });

    updateCheckoutAddressMap();
  }

  // ─── Auto dismiss alerts ─────────────────────────
  setTimeout(() => {
    document.querySelectorAll('.alert-auto').forEach(a => {
      a.style.opacity = '0';
      a.style.transition = 'opacity 0.5s';
      setTimeout(() => a.remove(), 500);
    });
  }, 3000);

  // ─── Live refresh for order/admin pages ─────────
  const liveRefreshTarget = document.querySelector('[data-live-refresh]');
  if (liveRefreshTarget) {
    const intervalMs = Number(liveRefreshTarget.dataset.liveRefresh || 15000);
    const liveRefreshSource = liveRefreshTarget.dataset.liveRefreshSource || '';
    let isReloading = false;
    let isFetching = false;

    const hasActiveEditor = () => {
      const activeElement = document.activeElement;
      if (!activeElement) return false;
      return ['INPUT', 'TEXTAREA', 'SELECT'].includes(activeElement.tagName) || activeElement.isContentEditable;
    };

    if (liveRefreshSource) {
      window.setInterval(async () => {
        if (document.hidden || hasActiveEditor() || isFetching) return;
        isFetching = true;

        try {
          const response = await fetch(liveRefreshSource, {
            headers: {
              'Accept': 'application/json',
              'X-Requested-With': 'XMLHttpRequest',
            },
            cache: 'no-store',
          });
          if (!response.ok) throw new Error(`Live refresh failed with status ${response.status}`);

          const data = await response.json();
          const fragments = data.fragments || {};
          Object.entries(fragments).forEach(([selector, html]) => {
            const element = document.querySelector(selector);
            if (!element || typeof html !== 'string') return;
            element.outerHTML = html;
          });
          initializeUiBindings(document);
        } catch (error) {
          console.error('Unable to refresh live sections.', error);
        } finally {
          isFetching = false;
        }
      }, intervalMs);
    } else {
      window.setInterval(() => {
        if (document.hidden || hasActiveEditor() || isReloading) return;
        isReloading = true;
        saveAdminScrollState();
        window.location.reload();
      }, intervalMs);
    }
  }

});

// ─── Chart initializer ────────────────────────────
function initCharts() {
  // Revenue Chart
  const revenueCtx = document.querySelector('#revenueChart');
  if (revenueCtx && window.Chart) {
    const labels   = JSON.parse(revenueCtx.dataset.labels || '[]');
    const revenues = JSON.parse(revenueCtx.dataset.revenues || '[]');

    new Chart(revenueCtx, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'Revenue (₹)',
          data: revenues,
          borderColor: '#C8873A',
          backgroundColor: 'rgba(200,135,58,0.1)',
          borderWidth: 2.5,
          fill: true,
          tension: 0.4,
          pointBackgroundColor: '#C8873A',
          pointRadius: 4
        }]
      },
      options: {
        responsive: true,
        plugins: {
          legend: { labels: { font: { family: 'DM Sans', size: 12 }, color: '#7A6A5A' } },
          tooltip: { backgroundColor: '#2C2418', titleColor: '#FDF6EC', bodyColor: '#FDF6EC' }
        },
        scales: {
          x: { grid: { color: 'rgba(92,61,46,0.06)' }, ticks: { color: '#7A6A5A', font: { family: 'DM Sans' } } },
          y:  { grid: { color: 'rgba(92,61,46,0.06)' }, ticks: { color: '#7A6A5A', font: { family: 'DM Sans' }, callback: v => '₹'+v } }
        }
      }
    });
  }

  const ordersCtx = document.querySelector('#ordersChart');
  if (ordersCtx && window.Chart) {
    const labels = JSON.parse(ordersCtx.dataset.labels || '[]');
    const orders = JSON.parse(ordersCtx.dataset.orders || '[]');

    new Chart(ordersCtx, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'Orders',
          data: orders,
          backgroundColor: 'rgba(122,158,126,0.85)',
          borderRadius: 10,
          borderSkipped: false
        }]
      },
      options: {
        responsive: true,
        plugins: {
          legend: { labels: { font: { family: 'DM Sans', size: 12 }, color: '#7A6A5A' } },
          tooltip: { backgroundColor: '#2C2418', titleColor: '#FDF6EC', bodyColor: '#FDF6EC' }
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: '#7A6A5A', font: { family: 'DM Sans' } } },
          y: { beginAtZero: true, grid: { color: 'rgba(92,61,46,0.06)' }, ticks: { precision: 0, color: '#7A6A5A', font: { family: 'DM Sans' } } }
        }
      }
    });
  }

  // Status Donut
  const statusCtx = document.querySelector('#statusChart');
  if (statusCtx && window.Chart) {
    const labels = JSON.parse(statusCtx.dataset.labels || '[]');
    const values = JSON.parse(statusCtx.dataset.values || '[]');
    new Chart(statusCtx, {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{ data: values, backgroundColor: ['#C8873A','#7A9E7E','#D4847A','#5C3D2E','#8B6148','#2C2418','#E8A84A'], borderWidth: 0, hoverOffset: 6 }]
      },
      options: {
        responsive: true, cutout: '70%',
        plugins: { legend: { position: 'bottom', labels: { font: { family: 'DM Sans' }, color: '#7A6A5A', padding: 12 } } }
      }
    });
  }
}

// ─── Format currency ──────────────────────────────
function formatINR(amount) {
  return '₹' + parseFloat(amount).toLocaleString('en-IN', { minimumFractionDigits: 2 });
}

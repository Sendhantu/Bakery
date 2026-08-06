/* Sweet Crumbs Bakery — Main JS */

document.addEventListener('DOMContentLoaded', () => {
  const formatCurrency = (value) => {
    const amount = Number(value || 0);
    return `₹${amount.toLocaleString('en-IN', {
      minimumFractionDigits: amount % 1 ? 2 : 0,
      maximumFractionDigits: 2,
    })}`;
  };

  const freeDeliveryBannerHtml = ({ subtotal = 0, threshold = 500, unlocked = false, count = 0 }) => {
    const itemCount = Number(count || 0);
    const freeDeliveryThreshold = Number(threshold || 0);
    if (itemCount <= 0 || freeDeliveryThreshold <= 0) return '';

    const cartSubtotal = Math.max(0, Number(subtotal || 0));
    const remaining = Math.max(0, freeDeliveryThreshold - cartSubtotal);
    const progress = Math.min(100, Math.max(0, Math.round((cartSubtotal / freeDeliveryThreshold) * 100)));
    const isUnlocked = Boolean(unlocked) || remaining <= 0;
    const message = isUnlocked
      ? `You've unlocked <strong>FREE delivery</strong> 🎁`
      : `Add ${formatCurrency(remaining)} more for <strong>FREE delivery</strong> 🎁`;

    return `
      <div class="free-delivery-banner${isUnlocked ? ' free-delivery-banner-unlocked' : ''}" data-free-delivery-banner>
        <p class="free-delivery-message">${message}</p>
        <div class="free-delivery-track" aria-hidden="true">
          <div class="free-delivery-track-fill" style="width:${progress}%"></div>
        </div>
      </div>
    `;
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
      const windowSeconds = Number(cancelTimer.dataset.cancelWindowSeconds || 120);
      targetTime.setSeconds(targetTime.getSeconds() + windowSeconds);
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

  const initPos = (root = document) => {
    const posRoot = root.querySelector?.('[data-pos-root], [data-pos-form]');
    if (!posRoot || posRoot.dataset.posBound === 'true') return;
    posRoot.dataset.posBound = 'true';

    const saleForm = posRoot.matches('form') ? posRoot : posRoot.querySelector('[data-pos-sale-form]');
    const cartInput = saleForm?.querySelector('[data-pos-cart-input]');
    const linesContainer = saleForm?.querySelector('[data-pos-cart-lines]');
    const emptyState = saleForm?.querySelector('[data-pos-empty]');
    const subtotalNode = saleForm?.querySelector('[data-pos-subtotal]');
    const cgstNode = saleForm?.querySelector('[data-pos-cgst]');
    const sgstNode = saleForm?.querySelector('[data-pos-sgst]');
    const totalNode = saleForm?.querySelector('[data-pos-total]');
    const submitButton = saleForm?.querySelector('[data-pos-submit]');
    const searchInput = posRoot.querySelector('[data-pos-search]');
    const lookupInput = posRoot.querySelector('[data-pos-lookup]');
    const lookupQuantity = posRoot.querySelector('[data-pos-lookup-qty]');
    const lookupButton = posRoot.querySelector('[data-pos-lookup-add]');
    const lookupStatus = posRoot.querySelector('[data-pos-lookup-status]');
    const productGrid = posRoot.querySelector('[data-pos-product-grid]');
    const gstRate = Number(posRoot.dataset.gstRate || saleForm?.dataset.gstRate || 5);
    const cart = new Map();
    const allTiles = () => Array.from(posRoot.querySelectorAll('[data-pos-add]'));

    const renderCart = () => {
      const items = Array.from(cart.values());
      if (cartInput) {
        cartInput.value = JSON.stringify(items.map((item) => ({
          variant_id: item.variantId,
          quantity: item.quantity,
        })));
      }
      if (emptyState) emptyState.style.display = items.length ? 'none' : '';
      if (submitButton) submitButton.disabled = items.length === 0;
      if (!linesContainer) return;

      linesContainer.querySelectorAll('[data-pos-line]').forEach((line) => line.remove());
      let total = 0;
      items.forEach((item) => {
        total += item.price * item.quantity;
        const row = document.createElement('div');
        row.className = 'pos-cart-line';
        row.dataset.posLine = item.variantId;
        row.innerHTML = `
          <div class="pos-cart-line-main">
            <strong></strong>
            <span>${formatCurrency(item.price)} each</span>
          </div>
          <div class="pos-stepper">
            <button type="button" data-pos-decrease="${item.variantId}" aria-label="Decrease quantity">-</button>
            <span>${item.quantity}</span>
            <button type="button" data-pos-increase="${item.variantId}" aria-label="Increase quantity">+</button>
          </div>
          <strong>${formatCurrency(item.price * item.quantity)}</strong>
          <button type="button" class="pos-remove" data-pos-remove="${item.variantId}" aria-label="Remove item">x</button>
        `;
        row.querySelector('strong').textContent = item.name;
        linesContainer.appendChild(row);
      });
      const gstAmount = Math.round(total * gstRate) / 100;
      const cgstAmount = Math.round((gstAmount / 2) * 100) / 100;
      const sgstAmount = Math.round((gstAmount - cgstAmount) * 100) / 100;
      if (subtotalNode) subtotalNode.textContent = formatCurrency(total);
      if (cgstNode) cgstNode.textContent = formatCurrency(cgstAmount);
      if (sgstNode) sgstNode.textContent = formatCurrency(sgstAmount);
      if (totalNode) totalNode.textContent = formatCurrency(total + gstAmount);
    };

    const updateQuantity = (variantId, delta) => {
      const item = cart.get(String(variantId));
      if (!item) return;
      item.quantity = Math.max(0, Math.min(item.stock, item.quantity + delta));
      if (item.quantity <= 0) cart.delete(String(variantId));
      renderCart();
    };

    const setLookupStatus = (message, isError = false) => {
      if (!lookupStatus) return;
      lookupStatus.textContent = message;
      lookupStatus.classList.toggle('text-danger', isError);
    };

    const addTileToCart = (tile, quantity = 1) => {
      const variantId = String(tile.dataset.variantId || '');
      const stock = Number(tile.dataset.stock || 0);
      const requestedQuantity = Math.max(1, Number(quantity || 1));
      if (!variantId || stock <= 0) {
        setLookupStatus('That item is out of stock.', true);
        return false;
      }
      const existing = cart.get(variantId);
      if (existing) {
        existing.quantity = Math.min(stock, existing.quantity + requestedQuantity);
      } else {
        cart.set(variantId, {
          variantId,
          name: tile.dataset.name || 'Product',
          price: Number(tile.dataset.price || 0),
          stock,
          quantity: Math.min(stock, requestedQuantity),
        });
      }
      tile.classList.add('rt-highlight');
      window.setTimeout(() => tile.classList.remove('rt-highlight'), 900);
      renderCart();
      setLookupStatus(`Added ${tile.dataset.name || 'item'} to the order.`);
      return true;
    };

    const normalizeLookup = (value) => (value || '').trim().toLowerCase().replace(/^#/, '');

    const findTileForLookup = (value) => {
      const query = normalizeLookup(value);
      if (!query) return null;
      const tiles = allTiles();
      const exactIdentityMatch = tiles.find((tile) => (
        normalizeLookup(tile.dataset.variantId) === query
        || normalizeLookup(tile.dataset.productId) === query
        || normalizeLookup(tile.dataset.sku) === query
        || normalizeLookup(tile.dataset.barcode) === query
      ) && Number(tile.dataset.stock || 0) > 0);
      if (exactIdentityMatch) return exactIdentityMatch;

      const exactNameMatch = tiles.find((tile) => (
        normalizeLookup(tile.dataset.name) === query
      ) && Number(tile.dataset.stock || 0) > 0);
      if (exactNameMatch) return exactNameMatch;

      return tiles.find((tile) => (
        normalizeLookup(tile.dataset.search).includes(query)
        || normalizeLookup(tile.dataset.name).includes(query)
      ) && Number(tile.dataset.stock || 0) > 0) || null;
    };

    const quickAddFromLookup = () => {
      const tile = findTileForLookup(lookupInput?.value);
      if (!tile) {
        setLookupStatus('No available item matched that ID or name.', true);
        lookupInput?.focus();
        return;
      }
      if (addTileToCart(tile, lookupQuantity?.value)) {
        if (lookupInput) lookupInput.value = '';
        if (lookupQuantity) lookupQuantity.value = '1';
        lookupInput?.focus();
      }
    };

    productGrid?.addEventListener('click', (event) => {
      const tile = event.target.closest('[data-pos-add]');
      if (!tile) return;
      addTileToCart(tile, 1);
    });

    lookupButton?.addEventListener('click', quickAddFromLookup);
    lookupInput?.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      quickAddFromLookup();
    });

    linesContainer?.addEventListener('click', (event) => {
      const increase = event.target.closest('[data-pos-increase]')?.dataset.posIncrease;
      const decrease = event.target.closest('[data-pos-decrease]')?.dataset.posDecrease;
      const remove = event.target.closest('[data-pos-remove]')?.dataset.posRemove;
      if (increase) updateQuantity(increase, 1);
      if (decrease) updateQuantity(decrease, -1);
      if (remove) {
        cart.delete(String(remove));
        renderCart();
      }
    });

    searchInput?.addEventListener('input', () => {
      const query = searchInput.value.trim().toLowerCase();
      productGrid?.querySelectorAll('[data-pos-product-card], [data-pos-add]').forEach((node) => {
        if (node.matches('[data-pos-add]') && node.closest('[data-pos-product-card]')) return;
        const haystack = (node.dataset.search || node.querySelector?.('[data-pos-add]')?.dataset.search || '').toLowerCase();
        node.hidden = Boolean(query) && !haystack.includes(query);
      });
    });

    saleForm?.addEventListener('submit', (event) => {
      renderCart();
      if (!cart.size) event.preventDefault();
    });

    renderCart();
  };

  const initAdminProductFormControls = (root = document) => {
    const addVariantButton = root.querySelector?.('#add-variant-btn');
    if (addVariantButton && addVariantButton.dataset.variantBound !== 'true') {
      addVariantButton.dataset.variantBound = 'true';
      addVariantButton.addEventListener('click', () => {
        const container = document.querySelector('#variants-container');
        const row = document.createElement('div');
        row.className = 'variant-row flex gap-2 items-center mt-2';
        row.innerHTML = `
          <input type="hidden" name="variant_id[]" value="">
          <input class="form-control" type="text" name="variant_name[]" placeholder="e.g. 1 kg" required>
          <input class="form-control" type="number" name="variant_price[]" placeholder="Price" required>
          <input class="form-control" type="number" name="variant_stock[]" placeholder="Stock">
          <button type="button" class="btn btn-ghost text-muted remove-variant-btn" style="flex-shrink:0">x</button>
        `;
        row.querySelector('.remove-variant-btn')?.addEventListener('click', () => row.remove());
        container?.appendChild(row);
      });
    }

    root.querySelectorAll?.('.remove-variant-btn').forEach((button) => {
      if (button.dataset.removeVariantBound === 'true') return;
      button.dataset.removeVariantBound = 'true';
      button.addEventListener('click', () => button.closest('.variant-row')?.remove());
    });

    const addMaterialButton = root.querySelector?.('#add-material-btn');
    if (addMaterialButton && addMaterialButton.dataset.materialBound !== 'true') {
      addMaterialButton.dataset.materialBound = 'true';
      addMaterialButton.addEventListener('click', () => {
        const container = document.querySelector('#materials-container');
        const firstRow = container?.querySelector('.material-row');
        if (!container || !firstRow) return;

        const row = firstRow.cloneNode(true);
        row.querySelectorAll('input').forEach((input) => { input.value = ''; });
        row.querySelectorAll('select').forEach((select) => { select.selectedIndex = 0; });
        row.querySelector('.remove-material-btn')?.addEventListener('click', () => row.remove());
        container.appendChild(row);
      });
    }

    root.querySelectorAll?.('.remove-material-btn').forEach((button) => {
      if (button.dataset.removeMaterialBound === 'true') return;
      button.dataset.removeMaterialBound = 'true';
      button.addEventListener('click', () => button.closest('.material-row')?.remove());
    });
  };

  const initPurchaseOrderFormControls = (root = document) => {
    root.querySelectorAll?.('[data-purchase-order-form]').forEach((form) => {
      if (form.dataset.purchaseOrderBound === 'true') return;
      form.dataset.purchaseOrderBound = 'true';

      const lines = form.querySelector('[data-po-lines]');
      const addButton = form.querySelector('[data-add-po-line]');
      const template = form.querySelector('template[data-po-line-template]');
      const help = form.querySelector('[data-po-line-help]');
      if (!lines || !addButton || !template) return;

      const rows = () => Array.from(lines.querySelectorAll('[data-po-line]'));
      const lineIsComplete = (row) => {
        const material = row.querySelector('[name="raw_material_id[]"]')?.value || '';
        const quantity = row.querySelector('[name="quantity[]"]')?.value || '';
        const unitCost = row.querySelector('[name="unit_cost[]"]')?.value || '';
        const quantityNumber = Number(quantity);
        const unitCostNumber = Number(unitCost);
        return Boolean(material)
          && quantity.trim() !== ''
          && Number.isFinite(quantityNumber)
          && quantityNumber > 0
          && unitCost.trim() !== ''
          && Number.isFinite(unitCostNumber)
          && unitCostNumber >= 0;
      };

      const updateControls = () => {
        const currentRows = rows();
        const canAdd = currentRows.length > 0 && currentRows.every(lineIsComplete);
        addButton.disabled = !canAdd;
        if (help) {
          help.textContent = canAdd
            ? 'Current material lines are complete. You can add another material.'
            : 'Fill the current material, quantity, and unit cost before adding another line.';
        }
        currentRows.forEach((row) => {
          const removeButton = row.querySelector('[data-remove-po-line]');
          if (removeButton) removeButton.hidden = currentRows.length === 1;
        });
      };

      const bindRow = (row) => {
        row.querySelectorAll('select, input').forEach((field) => {
          field.addEventListener('input', updateControls);
          field.addEventListener('change', updateControls);
        });
        row.querySelector('[data-remove-po-line]')?.addEventListener('click', () => {
          if (rows().length > 1) {
            row.remove();
          } else {
            row.querySelectorAll('select').forEach((select) => { select.selectedIndex = 0; });
            row.querySelectorAll('input').forEach((input) => { input.value = ''; });
          }
          updateControls();
        });
      };

      rows().forEach(bindRow);
      updateControls();

      addButton.addEventListener('click', () => {
        if (addButton.disabled || !rows().every(lineIsComplete)) return;
        const fragment = template.content.cloneNode(true);
        const row = fragment.querySelector('[data-po-line]');
        if (!row) return;
        lines.appendChild(row);
        bindRow(row);
        row.querySelector('select, input')?.focus();
        updateControls();
      });
    });
  };

  const createAiProductCard = (product) => {
    const card = document.createElement('div');
    card.className = 'ai-product-card';

    const title = document.createElement('div');
    title.className = 'ai-product-card-title';
    const price = Number(product?.price || 0);
    title.textContent = `${product?.name || 'Bakery item'} — ${formatCurrency(price)}`;
    card.appendChild(title);

    const meta = document.createElement('div');
    meta.className = 'ai-product-card-meta';
    meta.textContent = product?.category || 'Bakery pick';
    card.appendChild(meta);

    const description = document.createElement('div');
    description.className = 'ai-product-card-desc';
    description.textContent = product?.description || 'A delicious bakery choice.';
    card.appendChild(description);

    if (product?.detail_url) {
      const link = document.createElement('a');
      link.className = 'btn btn-outline btn-sm mt-2';
      link.href = product.detail_url;
      link.textContent = 'View & Order';
      card.appendChild(link);
    }

    return card;
  };

  const appendAiChatBubble = (log, role, message, {products = [], addons = [], loading = false, error = false} = {}) => {
    if (!log) return null;
    log.querySelectorAll('[data-ai-chat-empty]').forEach((node) => node.remove());

    const bubble = document.createElement('div');
    bubble.className = `ai-chat-bubble ai-chat-bubble--${role}`;
    if (loading) bubble.classList.add('ai-chat-bubble--loading');
    if (error) bubble.classList.add('ai-chat-bubble--error');

    const author = document.createElement('div');
    author.className = 'ai-chat-author';
    author.textContent = role === 'user' ? 'You' : 'SweetCrumbs AI';
    bubble.appendChild(author);

    const text = document.createElement('div');
    text.className = 'ai-chat-text';
    text.textContent = message || '';
    bubble.appendChild(text);

    const productList = Array.isArray(products) ? products : [];
    if (productList.length) {
      const productsWrap = document.createElement('div');
      productsWrap.className = 'ai-products';
      productList.forEach((product) => productsWrap.appendChild(createAiProductCard(product)));
      bubble.appendChild(productsWrap);
    }

    const addonList = Array.isArray(addons) ? addons : [];
    if (addonList.length) {
      const addonTitle = document.createElement('div');
      addonTitle.className = 'ai-chat-section-title';
      addonTitle.textContent = 'Useful add-ons';
      bubble.appendChild(addonTitle);

      const addonsWrap = document.createElement('div');
      addonsWrap.className = 'ai-products';
      addonList.forEach((product) => addonsWrap.appendChild(createAiProductCard(product)));
      bubble.appendChild(addonsWrap);
    }

    const time = document.createElement('div');
    time.className = 'msg-time';
    time.textContent = new Date().toLocaleTimeString('en-IN', {
      hour: '2-digit',
      minute: '2-digit',
    });
    bubble.appendChild(time);

    log.appendChild(bubble);
    log.scrollTop = log.scrollHeight;
    return bubble;
  };

  const initAiChatAssistant = (root = document) => {
    root.querySelectorAll?.('[data-ai-chat]').forEach((panel) => {
      if (panel.dataset.aiChatBound === 'true') return;
      panel.dataset.aiChatBound = 'true';

      const form = panel.querySelector('[data-ai-chat-form]');
      const input = panel.querySelector('[data-ai-chat-input]');
      const submit = panel.querySelector('[data-ai-chat-submit]');
      const log = panel.querySelector('[data-ai-chat-log]');
      const endpoint = panel.dataset.aiEndpoint || '/chat/ai';
      const surface = panel.dataset.aiSurface || 'customer';
      if (!form || !input || !log) return;

      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const query = input.value.trim();
        if (!query) {
          appendAiChatBubble(log, 'assistant', 'Please type what you would like help with.', {error: true});
          input.focus();
          return;
        }

        const pageScrollY = window.scrollY;
        appendAiChatBubble(log, 'user', query);
        input.value = '';
        if (submit) {
          submit.disabled = true;
          submit.dataset.originalText = submit.dataset.originalText || submit.textContent;
          submit.textContent = 'Thinking...';
        }
        const loadingBubble = appendAiChatBubble(log, 'assistant', 'Finding the best bakery recommendations for you...', {loading: true});
        window.requestAnimationFrame(() => window.scrollTo({top: pageScrollY, behavior: 'auto'}));

        try {
          const response = await fetch(endpoint, {
            method: 'POST',
            headers: withCsrfHeaders({
              'Content-Type': 'application/json',
              'Accept': 'application/json',
            }),
            credentials: 'same-origin',
            body: JSON.stringify({query, surface}),
          });
          const result = await response.json();
          if (!response.ok || !result.ok) {
            throw new Error(result.message || 'Unable to get recommendations.');
          }

          loadingBubble?.remove();
          appendAiChatBubble(log, 'assistant', result.message || 'Here are some bakery picks for you.', {
            products: result.products || [],
            addons: result.checkout_addons || [],
          });
          window.requestAnimationFrame(() => window.scrollTo({top: pageScrollY, behavior: 'auto'}));
        } catch (error) {
          console.error(error);
          loadingBubble?.remove();
          appendAiChatBubble(log, 'assistant', error.message || 'Something went wrong while fetching recommendations. Please try again.', {
            error: true,
          });
          window.requestAnimationFrame(() => window.scrollTo({top: pageScrollY, behavior: 'auto'}));
        } finally {
          if (submit) {
            submit.disabled = false;
            submit.textContent = submit.dataset.originalText || 'Ask AI';
          }
          input.focus({preventScroll: true});
        }
      });
    });
  };

  const initShopAiWidget = (root = document) => {
    const widget = root.querySelector('[data-ai-shop-widget]');
    if (!widget || widget.dataset.aiShopBound === 'true') return;
    widget.dataset.aiShopBound = 'true';

    const fab = widget.querySelector('[data-ai-shop-toggle]');
    const panel = widget.querySelector('[data-ai-shop-panel]');
    const log = widget.querySelector('[data-ai-shop-log]');
    const form = widget.querySelector('[data-ai-shop-form]');
    const input = widget.querySelector('[data-ai-shop-input]');
    const submit = widget.querySelector('[data-ai-shop-submit]');
    const clearBtn = widget.querySelector('[data-ai-shop-clear]');
    const minimizeBtn = widget.querySelector('[data-ai-shop-minimize]');
    const loginPrompt = widget.querySelector('[data-ai-shop-login]');
    if (!panel || !log || !input || !form) return;

    const endpoint = widget.dataset.aiEndpoint || '/chat/ai';
    const surface = widget.dataset.aiSurface || 'shop';
    const cartUrl = widget.dataset.aiCartUrl || '/cart/add';
    let authenticated = widget.dataset.aiAuthenticated === 'true';
    const loginUrl = widget.dataset.aiLoginUrl || '';
    const registerUrl = widget.dataset.aiRegisterUrl || '';

    const storageKey = 'sweetcrumbs:shop-ai-chat:v1';
    const welcomeMessage = 'Hi! I can help you find cakes, pastries, breads, and other bakery products. What are you looking for today?';
    const suggestions = [
      '🎂 Show me chocolate cakes',
      '🌿 Suggest an eggless cake under ₹1,000',
      '🎉 I need a birthday cake for 10 people',
      '🚚 Show products available for delivery today',
    ];

    let open = false;
    let pendingQuery = '';
    let addInFlight = false;
    let lastAddMessage = '';
    let lastAddAt = 0;
    let lastAssistantProducts = [];
    let lastInteractedProductId = null;
    let surfacedProducts = [];
    let lastQuery = '';
    let chatLoaded = false;

    const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;',
    }[c]));

    const loadChat = () => {
      try {
        const raw = window.sessionStorage?.getItem(storageKey);
        if (!raw) return;
        const saved = JSON.parse(raw);
        if (Array.isArray(saved.messages)) {
          log.innerHTML = '';
          saved.messages.forEach((message) => renderSavedMessage(message));
          surfacedProducts = Array.isArray(saved.surfacedProducts) ? saved.surfacedProducts : [];
          lastQuery = saved.lastQuery || '';
          chatLoaded = saved.messages.some((m) => m.role === 'assistant');
          if (saved.lastInteractedProductId) lastInteractedProductId = saved.lastInteractedProductId;
        }
      } catch (error) {
        console.error('Unable to restore AI chat:', error);
      }
    };

    const saveChat = () => {
      try {
        const messages = [];
        log.querySelectorAll('[data-shop-bubble]').forEach((bubble) => {
          let bubbleProducts = [];
          if (bubble.dataset.shopProducts) {
            try {
              bubbleProducts = JSON.parse(bubble.dataset.shopProducts);
            } catch (jsonError) {
              bubbleProducts = [];
            }
          }
          messages.push({
            role: bubble.dataset.shopBubble,
            text: bubble.dataset.shopText || '',
            products: bubbleProducts,
            error: bubble.classList.contains('ai-chat-bubble--error'),
            isSystem: bubble.classList.contains('ai-chat-bubble--system'),
          });
        });
        window.sessionStorage?.setItem(storageKey, JSON.stringify({
          messages,
          surfacedProducts,
          lastQuery,
          lastInteractedProductId,
        }));
      } catch (error) {
        console.error('Unable to persist AI chat:', error);
      }
    };

    const renderSavedMessage = (message) => {
      if (message.isSystem) {
        appendBubble('system', message.text, {error: message.error, persist: false});
        return;
      }
      if (message.role === 'user') {
        appendBubble('user', message.text, {persist: false});
      } else if (message.role === 'assistant') {
        appendBubble('assistant', message.text, {
          products: message.products || [],
          error: message.error,
          persist: false,
        });
      }
    };

    const stars = (rating) => {
      const value = Math.max(0, Math.round(Number(rating) || 0));
      return '★'.repeat(value) + '☆'.repeat(5 - value);
    };

    const stockLabel = (product) => {
      const status = product.stock_status || 'in_stock';
      if (status === 'out_of_stock' || Number(product.stock) <= 0) {
        return {text: 'Out of Stock', cls: 'ai-shop-stock-out'};
      }
      if (status === 'few_left') {
        return {text: '⚠ Few Left', cls: 'ai-shop-stock-few'};
      }
      return {text: 'In Stock', cls: 'ai-shop-stock-in'};
    };

    const createProductCard = (product) => {
      const card = document.createElement('article');
      card.className = 'ai-shop-product-card';
      card.dataset.shopProductId = product.id;
      card.setAttribute('aria-label', `${product.name}, ${formatCurrency(product.price)}`);

      const imgWrap = document.createElement('div');
      imgWrap.className = 'ai-shop-product-img-wrap';
      const img = document.createElement('img');
      img.className = 'ai-shop-product-img';
      img.loading = 'lazy';
      img.decoding = 'async';
      img.alt = product.name || 'Bakery product';
      img.src = product.image || '';
      img.onerror = function () { this.onerror = null; this.style.visibility = 'hidden'; };
      imgWrap.appendChild(img);
      card.appendChild(imgWrap);

      const body = document.createElement('div');
      body.className = 'ai-shop-product-body';

      const badges = document.createElement('div');
      badges.className = 'ai-shop-product-badges';
      const stock = stockLabel(product);
      const stockBadge = document.createElement('span');
      stockBadge.className = `ai-shop-badge ${stock.cls}`;
      stockBadge.textContent = stock.text;
      badges.appendChild(stockBadge);
      if (product.eggless) {
        const egg = document.createElement('span');
        egg.className = 'ai-shop-badge ai-shop-badge-eggless';
        egg.textContent = '🌿 Eggless';
        badges.appendChild(egg);
      }
      if (product.preorder_required) {
        const pre = document.createElement('span');
        pre.className = 'ai-shop-badge ai-shop-badge-preorder';
        pre.textContent = `Preorder ${product.minimum_notice_hours || 24}h`;
        badges.appendChild(pre);
      }
      body.appendChild(badges);

      const title = document.createElement('h4');
      title.className = 'ai-shop-product-title';
      title.textContent = product.name || 'Bakery item';
      body.appendChild(title);

      const priceRow = document.createElement('div');
      priceRow.className = 'ai-shop-product-price-row';
      const price = document.createElement('span');
      price.className = 'ai-shop-product-price';
      price.textContent = formatCurrency(product.current_price || product.price);
      priceRow.appendChild(price);
      if (Number(product.base_price) > Number(product.current_price || product.price)) {
        const oldPrice = document.createElement('del');
        oldPrice.className = 'ai-shop-product-old-price';
        oldPrice.textContent = formatCurrency(product.base_price);
        priceRow.appendChild(oldPrice);
      }
      body.appendChild(priceRow);

      if (Number(product.rating) > 0) {
        const ratingRow = document.createElement('div');
        ratingRow.className = 'ai-shop-product-rating';
        const starEl = document.createElement('span');
        starEl.className = 'stars';
        starEl.textContent = stars(product.rating);
        ratingRow.appendChild(starEl);
        const count = document.createElement('span');
        count.className = 'ai-shop-product-reviews';
        count.textContent = `(${Number(product.review_count) || 0})`;
        ratingRow.appendChild(count);
        body.appendChild(ratingRow);
      }

      if (product.description) {
        const desc = document.createElement('p');
        desc.className = 'ai-shop-product-desc';
        const text = String(product.description);
        desc.textContent = text.length > 90 ? `${text.slice(0, 90)}…` : text;
        body.appendChild(desc);
      }

      const actions = document.createElement('div');
      actions.className = 'ai-shop-product-actions';
      const detailLink = document.createElement('a');
      detailLink.className = 'btn btn-outline btn-sm';
      detailLink.href = product.detail_url || `${widget.dataset.aiDetailBase || '/product/'}${product.id}`;
      detailLink.textContent = 'View Details';
      detailLink.setAttribute('aria-label', `View details for ${product.name}`);
      detailLink.addEventListener('click', () => {
        lastInteractedProductId = product.id;
      });
      actions.appendChild(detailLink);

      const available = stock.text !== 'Out of Stock';
      if (available) {
        const addButton = document.createElement('button');
        addButton.type = 'button';
        addButton.className = 'btn btn-primary btn-sm';
        addButton.textContent = '🛒 Add to Cart';
        addButton.setAttribute('aria-label', `Add ${product.name} to cart`);
        addButton.dataset.shopAddProduct = product.id;
        addButton.addEventListener('click', (event) => {
          event.preventDefault();
          lastInteractedProductId = product.id;
          startProductFlow(product, {fromMessage: false});
        });
        actions.appendChild(addButton);
      } else {
        const sold = document.createElement('span');
        sold.className = 'ai-shop-sold-out';
        sold.textContent = 'Sold Out';
        actions.appendChild(sold);
      }
      body.appendChild(actions);
      card.appendChild(body);
      return card;
    };

    const appendBubble = (role, text, {products = [], error = false, persist = true} = {}) => {
      const bubble = document.createElement('div');
      bubble.className = `ai-chat-bubble ai-chat-bubble--${role === 'user' ? 'user' : 'assistant'}`;
      if (error) bubble.classList.add('ai-chat-bubble--error');
      if (role === 'system') bubble.classList.add('ai-chat-bubble--system');
      bubble.dataset.shopBubble = role === 'user' ? 'user' : (role === 'system' ? 'system' : 'assistant');
      bubble.dataset.shopText = text || '';
      bubble.dataset.shopProducts = JSON.stringify(products || []);

      const author = document.createElement('div');
      author.className = 'ai-chat-author';
      author.textContent = role === 'user' ? 'You' : (role === 'system' ? 'Note' : 'SweetCrumbs AI');
      bubble.appendChild(author);

      const textEl = document.createElement('div');
      textEl.className = 'ai-chat-text';
      textEl.textContent = text || '';
      bubble.appendChild(textEl);

      if (products && products.length) {
        const wrap = document.createElement('div');
        wrap.className = 'ai-products ai-shop-products';
        products.forEach((product) => wrap.appendChild(createProductCard(product)));
        bubble.appendChild(wrap);
      }

      const time = document.createElement('div');
      time.className = 'msg-time';
      time.textContent = new Date().toLocaleTimeString('en-IN', {hour: '2-digit', minute: '2-digit'});
      bubble.appendChild(time);

      log.appendChild(bubble);
      log.scrollTop = log.scrollHeight;
      if (persist) saveChat();
      return bubble;
    };

    const appendActionButtons = (bubble, actions) => {
      const wrap = document.createElement('div');
      wrap.className = 'ai-shop-actions';
      actions.forEach((action) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `btn btn-sm ${action.cls || 'btn-ghost'}`;
        button.textContent = action.label;
        if (action.href) {
          button.addEventListener('click', () => { window.location.href = action.href; });
        } else if (action.onClick) {
          button.addEventListener('click', action.onClick);
        }
        if (action.primary) button.classList.add('ai-shop-action-primary');
        wrap.appendChild(button);
      });
      bubble.appendChild(wrap);
      log.scrollTop = log.scrollHeight;
    };

    const appendTyping = () => {
      const bubble = document.createElement('div');
      bubble.className = 'ai-chat-bubble ai-chat-bubble--assistant ai-chat-bubble--loading';
      bubble.dataset.shopTyping = 'true';
      const author = document.createElement('div');
      author.className = 'ai-chat-author';
      author.textContent = 'SweetCrumbs AI';
      bubble.appendChild(author);
      const text = document.createElement('div');
      text.className = 'ai-chat-text';
      text.innerHTML = '<span class="ai-typing-dots"><span>.</span><span>.</span><span>.</span></span>';
      bubble.appendChild(text);
      log.appendChild(bubble);
      log.scrollTop = log.scrollHeight;
      return bubble;
    };

    const setPanelOpen = (nextOpen, {focus = false} = {}) => {
      open = nextOpen;
      panel.classList.toggle('is-open', nextOpen);
      panel.setAttribute('aria-hidden', nextOpen ? 'false' : 'true');
      if (fab) fab.setAttribute('aria-expanded', nextOpen ? 'true' : 'false');
      if (nextOpen) {
        if (authenticated) {
          loginPrompt?.setAttribute('hidden', '');
          form.style.display = '';
          renderInitialContent();
        } else {
          renderLoginRequired();
        }
        if (focus) requestAnimationFrame(() => input?.focus({preventScroll: true}));
      } else {
        if (focus && fab) fab.focus({preventScroll: true});
        input?.blur();
      }
    };

    const renderLoginRequired = () => {
      log.innerHTML = '';
      form.style.display = 'none';
      if (loginPrompt) {
        loginPrompt.removeAttribute('hidden');
        const title = loginPrompt.querySelector('.ai-shop-login-title');
        const textEl = loginPrompt.querySelector('.ai-shop-login-text');
        const loginLink = loginPrompt.querySelector('.ai-shop-login-card a.btn-primary');
        const registerLink = loginPrompt.querySelector('.ai-shop-login-card a.btn-outline');
        if (loginLink && loginUrl) loginLink.href = loginUrl;
        if (registerLink && registerUrl) registerLink.href = registerUrl;
        if (loginPrompt.dataset.expired === 'true') {
          if (title) title.textContent = 'Session Expired';
          if (textEl) textEl.textContent = 'Your session has expired. Please log in again to keep chatting.';
        }
      }
    };

    const renderInitialContent = () => {
      if (loginPrompt) loginPrompt.setAttribute('hidden', '');
      form.style.display = '';
      if (!chatLoaded) {
        log.innerHTML = '';
        appendBubble('assistant', welcomeMessage, {persist: true});
        renderSuggestionChips();
        chatLoaded = true;
        saveChat();
      }
    };

    const renderSuggestionChips = () => {
      const existing = log.querySelector('[data-shop-suggestions]');
      if (existing) return;
      const wrap = document.createElement('div');
      wrap.className = 'ai-shop-suggestions';
      wrap.dataset.shopSuggestions = 'true';
      suggestions.forEach((suggestion) => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'ai-shop-suggestion-chip';
        chip.textContent = suggestion;
        chip.addEventListener('click', () => sendUserMessage(suggestion));
        wrap.appendChild(chip);
      });
      log.appendChild(wrap);
      log.scrollTop = log.scrollHeight;
    };

    const collectSurfacedProducts = () => {
      if (!lastAssistantProducts.length) return [];
      const seen = new Set();
      const result = [];
      lastAssistantProducts.forEach((product) => {
        if (!seen.has(product.id)) {
          seen.add(product.id);
          result.push(product);
        }
      });
      surfacedProducts.forEach((product) => {
        if (!seen.has(product.id)) {
          seen.add(product.id);
          result.push(product);
        }
      });
      return result;
    };

    const ordinalIndex = (text) => {
      const match = String(text).toLowerCase().match(/\b(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th)\b/);
      if (!match) return -1;
      const map = {first: 0, second: 1, third: 2, fourth: 3, fifth: 4, '1st': 0, '2nd': 1, '3rd': 2, '4th': 3, '5th': 4};
      return map[match[1]];
    };

    const findProductByName = (text) => {
      const lower = String(text).toLowerCase();
      const all = collectSurfacedProducts();
      const matches = all.filter((product) => {
        const name = String(product.name || '').toLowerCase();
        return name && lower.includes(name);
      });
      if (matches.length === 1) return matches[0];
      if (matches.length > 1) return 'ambiguous';
      return null;
    };

    const resolveAddToCartTarget = (message) => {
      const index = ordinalIndex(message);
      if (index >= 0) {
        const all = collectSurfacedProducts();
        return all[index] || null;
      }
      const lower = message.toLowerCase();
      if (/\b(this|that|it)\b/.test(lower)) {
        if (lastInteractedProductId) {
          const target = collectSurfacedProducts().find((p) => p.id === lastInteractedProductId);
          if (target) return target;
        }
        return lastAssistantProducts[0] || null;
      }
      return findProductByName(message);
    };

    const handleAddToCartIntent = (message) => {
      const text = String(message || '').trim();
      if (!text) return false;
      const addToCartPattern = /\b(?:add|put|place)\b[\s\S]*\b(?:to\s+(?:my\s+|the\s+|your\s+)?(?:cart|bag)|in(?:to)?\s+(?:my\s+|the\s+|your\s+)?(?:cart|bag))\b/i;
      const wantOrdinalPattern = /\b(?:i(?:'ll| would)?\s+(?:take|like|want)|take)\b/i;
      const looksLikeAdd = addToCartPattern.test(text) || (wantOrdinalPattern.test(text) && ordinalIndex(text) >= 0);
      if (!looksLikeAdd) return false;

      const now = Date.now();
      if (text === lastAddMessage && now - lastAddAt < 5000) {
        appendBubble('assistant', 'That item is already being added. Give it a moment.', {persist: true});
        return true;
      }

      const target = resolveAddToCartTarget(text);
      if (target === 'ambiguous') {
        appendBubble('assistant', 'I found a few products with that name. Which one would you like to add?', {persist: true});
        askToChooseProducts(collectSurfacedProducts());
        lastAddMessage = text;
        lastAddAt = now;
        return true;
      }
      if (!target) {
        if (surfacedProducts.length) {
          appendBubble('assistant', 'I couldn\'t tell which product you mean. Please pick one, or name the exact product.', {persist: true});
          askToChooseProducts(collectSurfacedProducts());
        } else {
          appendBubble('assistant', 'I couldn\'t find that product in our conversation yet. Try searching for it first, e.g. “show me chocolate cakes”.', {persist: true});
        }
        lastAddMessage = text;
        lastAddAt = now;
        return true;
      }
      lastAddMessage = text;
      lastAddAt = now;
      startProductFlow(target, {fromMessage: true});
      return true;
    };

    const handleProductDetailIntent = (message) => {
      const text = String(message || '').toLowerCase();
      const pattern = /\b(tell\s+me\s+more|more\s+about|view|show\s+me)\b/.test(text)
        && /\b(product|one|this|that|it)\b/.test(text);
      if (!pattern) return false;
      let target = null;
      const index = ordinalIndex(text);
      if (index >= 0) {
        target = collectSurfacedProducts()[index];
      } else if (/\b(this|that|it)\b/.test(text)) {
        target = lastInteractedProductId
          ? collectSurfacedProducts().find((p) => p.id === lastInteractedProductId)
          : lastAssistantProducts[0];
      }
      if (!target) return false;
      window.location.href = target.detail_url || `${widget.dataset.aiDetailBase || '/product/'}${target.id}`;
      return true;
    };

    const composeFollowUpQuery = (message) => {
      const text = String(message || '').trim().toLowerCase();
      if (!lastQuery) return null;
      const followUp = /\b(cheap|cheaper|affordable|eggless|more|different|other|what\s+about)\b/.test(text);
      if (!followUp) return null;
      const parts = [lastQuery];
      if (/\b(cheap|cheaper|affordable)\b/.test(text)) parts.push('cheaper');
      if (/\beggless\b/.test(text)) parts.push('eggless');
      return parts.join(' ');
    };

    const sendUserMessage = (message) => {
      const text = String(message || '').trim();
      if (!text) return;
      if (!authenticated) {
        renderLoginRequired();
        appendBubble('assistant', 'Please log in to use our AI bakery assistant.', {persist: false});
        return;
      }

      appendBubble('user', text, {persist: true});
      input.value = '';

      if (handleAddToCartIntent(text)) {
        saveChat();
        return;
      }
      if (handleProductDetailIntent(text)) {
        return;
      }

      const composed = composeFollowUpQuery(text);
      const query = composed || text;
      if (composed) lastQuery = query;
      pendingQuery = text;
      sendShopQuery(query);
    };

    const sendShopQuery = async (query) => {
      if (submit) {
        submit.disabled = true;
        submit.textContent = '…';
      }
      const typing = appendTyping();
      const history = [];
      log.querySelectorAll('[data-shop-bubble="user"], [data-shop-bubble="assistant"]').forEach((bubble) => {
        const role = bubble.dataset.shopBubble;
        const content = bubble.dataset.shopText;
        if (content) history.push({role, content});
      });

      try {
        const response = await fetch(endpoint, {
          method: 'POST',
          headers: withCsrfHeaders({
            'Content-Type': 'application/json',
            'Accept': 'application/json',
          }),
          credentials: 'same-origin',
          body: JSON.stringify({query, surface, history}),
        });
        let result = null;
        try {
          result = await response.json();
        } catch (jsonError) {
          result = null;
        }

        typing?.remove();

        if (response.status === 401 || (result && result.code === 'auth_required')) {
          authenticated = false;
          widget.dataset.aiAuthenticated = 'false';
          if (loginPrompt) loginPrompt.dataset.expired = 'true';
          renderLoginRequired();
          appendBubble('assistant', result?.message || 'Please log in again to continue.', {persist: true});
          return;
        }
        if (!response.ok || !result || !result.ok) {
          throw new Error(result?.message || 'Unable to get recommendations.');
        }

        lastQuery = query;
        if (Array.isArray(result.products)) {
          lastAssistantProducts = result.products;
          surfacedProducts = collectSurfacedProducts();
        }
        appendBubble('assistant', result.message || 'Here are some bakery picks for you.', {
          products: result.products || [],
        });
        if (!(result.products || []).length) {
          appendActionButtons(appendBubble('system', 'No matching products were found. Try a different search or ask for something else.', {persist: true}), [
            {label: 'Try again', cls: 'btn-outline', onClick: () => sendShopQuery(pendingQuery || lastQuery)},
          ]);
        }
      } catch (error) {
        console.error(error);
        typing?.remove();
        const errorBubble = appendBubble('assistant', error.message || 'Something went wrong. Please try again.', {error: true, persist: true});
        appendActionButtons(errorBubble, [
          {label: 'Retry', cls: 'btn-outline', primary: true, onClick: () => sendShopQuery(pendingQuery || lastQuery)},
        ]);
      } finally {
        if (submit) {
          submit.disabled = false;
          submit.textContent = 'Send';
        }
        input.focus({preventScroll: true});
      }
    };

    const askToChooseProducts = (products) => {
      const list = (products || []).slice(0, 6);
      if (!list.length) return;
      const bubble = appendBubble('assistant', 'Tap a product to add it to your cart:', {persist: true});
      const wrap = document.createElement('div');
      wrap.className = 'ai-shop-picker';
      list.forEach((product, index) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'ai-shop-picker-option';
        const stock = stockLabel(product);
        button.innerHTML = `<strong>${escapeHtml(product.name)}</strong> <span>${formatCurrency(product.current_price || product.price)} · ${stock.text}</span>`;
        if (stock.text === 'Out of Stock') button.disabled = true;
        button.setAttribute('aria-label', `Add ${product.name} to cart`);
        button.addEventListener('click', () => {
          lastInteractedProductId = product.id;
          startProductFlow(product, {fromMessage: false});
        });
        wrap.appendChild(button);
      });
      bubble.appendChild(wrap);
      log.scrollTop = log.scrollHeight;
    };

    const startProductFlow = (product, {fromMessage = false}) => {
      if (addInFlight) {
        appendBubble('assistant', 'One moment — I\'m still finishing the previous cart update.', {persist: true});
        return;
      }
      const stock = stockLabel(product);
      if (stock.text === 'Out of Stock') {
        const bubble = appendBubble('assistant', `${product.name} is currently out of stock, so I can't add it. Here are some alternatives:`, {persist: true});
        const alternatives = (collectSurfacedProducts() || []).filter((p) => p.id !== product.id && stockLabel(p).text !== 'Out of Stock').slice(0, 3);
        if (alternatives.length) {
          const wrap = document.createElement('div');
          wrap.className = 'ai-shop-picker';
          alternatives.forEach((alt) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'ai-shop-picker-option';
            button.innerHTML = `<strong>${escapeHtml(alt.name)}</strong> <span>${formatCurrency(alt.current_price || alt.price)}</span>`;
            button.addEventListener('click', () => {
              lastInteractedProductId = alt.id;
              startProductFlow(alt, {fromMessage: false});
            });
            wrap.appendChild(button);
          });
          bubble.appendChild(wrap);
        } else {
          bubble.querySelector('.ai-chat-text').textContent += ' Ask me to search for something similar.';
        }
        log.scrollTop = log.scrollHeight;
        return;
      }

      const variants = (product.variants || []).filter((variant) => Number(variant.stock) > 0);
      if (!variants.length) {
        appendBubble('assistant', `${product.name} has no available options in stock right now. Please pick something else.`, {persist: true});
        return;
      }
      if (variants.length === 1) {
        startQuantityFlow(product, variants[0]);
        return;
      }
      const bubble = appendBubble('assistant', `${product.name} is available in these options. Which size would you like?`, {persist: true});
      const wrap = document.createElement('div');
      wrap.className = 'ai-shop-picker';
      variants.forEach((variant) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'ai-shop-picker-option';
        button.innerHTML = `<strong>${escapeHtml(variant.name)}</strong> <span>${formatCurrency(variant.price)}</span>`;
        button.setAttribute('aria-label', `Choose ${variant.name} for ${product.name}`);
        button.addEventListener('click', () => startQuantityFlow(product, variant));
        wrap.appendChild(button);
      });
      bubble.appendChild(wrap);
      log.scrollTop = log.scrollHeight;
    };

    const startQuantityFlow = (product, variant) => {
      const bubble = appendBubble('assistant', `How many ${product.name} (${variant.name}) would you like?`, {persist: true});
      const wrap = document.createElement('div');
      wrap.className = 'ai-shop-picker ai-shop-quantity';
      [1, 2, 3, 5].forEach((quantity) => {
        if (Number(variant.stock) >= quantity) {
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'ai-shop-picker-option';
          button.textContent = String(quantity);
          button.setAttribute('aria-label', `Add ${quantity} of ${product.name}`);
          button.addEventListener('click', () => submitAddToCart(product, variant, quantity));
          wrap.appendChild(button);
        }
      });
      bubble.appendChild(wrap);
      log.scrollTop = log.scrollHeight;
    };

    const submitAddToCart = async (product, variant, quantity) => {
      if (addInFlight) return;
      addInFlight = true;
      if (submit) submit.disabled = true;

      const typing = appendTyping();
      try {
        const body = new FormData();
        body.set('product_id', product.id);
        body.set('variant_id', variant.id);
        body.set('quantity', String(quantity));

        const response = await fetch(cartUrl, {
          method: 'POST',
          headers: withCsrfHeaders({
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json',
          }),
          credentials: 'same-origin',
          body,
        });
        typing?.remove();
        let data = null;
        try {
          data = await response.json();
        } catch (jsonError) {
          data = null;
        }

        if (response.status === 401 || (data && data.code === 'auth_required')) {
          authenticated = false;
          widget.dataset.aiAuthenticated = 'false';
          if (loginPrompt) loginPrompt.dataset.expired = 'true';
          renderLoginRequired();
          appendBubble('assistant', 'Please log in again to add items to your cart.', {persist: true});
          return;
        }
        if (!response.ok || !data || !data.ok) {
          throw new Error(data?.message || 'Unable to add the product to cart.');
        }

        if (typeof setCartBadge === 'function') setCartBadge(data.count || 0);
        if (typeof renderMiniCart === 'function') renderMiniCart(data);

        const confirm = appendBubble('assistant', `${product.name} has been added to your cart.`, {persist: true});
        const details = document.createElement('div');
        details.className = 'ai-shop-add-details';
        details.textContent = `${variant.name} · Qty ${quantity} · ${formatCurrency(Number(variant.price || 0) * quantity)}`;
        confirm.appendChild(details);
        const updated = document.createElement('div');
        updated.className = 'ai-shop-add-count';
        updated.textContent = `Your bag now has ${data.count || 0} item${data.count === 1 ? '' : 's'}.`;
        confirm.appendChild(updated);
        if (product.preorder_required) {
          const note = document.createElement('div');
          note.className = 'ai-shop-add-note';
          note.textContent = `Preorder item — pick a delivery date at checkout.`;
          confirm.appendChild(note);
        }
        appendActionButtons(confirm, [
          {label: 'View Cart', cls: 'btn-outline', href: data.cart_url},
          {label: 'Checkout', cls: 'btn-primary', href: data.checkout_url, primary: true},
        ]);
      } catch (error) {
        console.error(error);
        typing?.remove();
        const errorBubble = appendBubble('assistant', error.message || 'Something went wrong while adding to cart.', {error: true, persist: true});
        appendActionButtons(errorBubble, [
          {label: 'Retry', cls: 'btn-outline', primary: true, onClick: () => submitAddToCart(product, variant, quantity)},
        ]);
      } finally {
        addInFlight = false;
        if (submit) submit.disabled = false;
        input.focus({preventScroll: true});
      }
    };

    const clearChat = () => {
      const confirmed = window.confirm('Clear this AI chat? This will start a fresh conversation.');
      if (!confirmed) return;
      try {
        window.sessionStorage?.removeItem(storageKey);
      } catch (error) {
        console.error(error);
      }
      log.innerHTML = '';
      chatLoaded = false;
      lastQuery = '';
      pendingQuery = '';
      lastAssistantProducts = [];
      lastInteractedProductId = null;
      surfacedProducts = [];
      renderInitialContent();
    };

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const query = input.value.trim();
      if (!query) return;
      sendUserMessage(query);
    });

    fab?.addEventListener('click', () => {
      setPanelOpen(!open, {focus: true});
    });

    minimizeBtn?.addEventListener('click', () => setPanelOpen(false, {focus: true}));
    clearBtn?.addEventListener('click', clearChat);

    panel.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        setPanelOpen(false, {focus: true});
      }
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && open) {
        setPanelOpen(false, {focus: true});
      }
    });

    loadChat();
    if (open) {
      setPanelOpen(true);
    }
  };

  const initializeUiBindings = (root = document) => {
    applyCsrfToForms(root);
    initImageFallbacks(root);
    initConfirmDialogs(root);
    initToggleTargets(root);
    initMapToggles(root);
    initCancelTimers(root);
    initPos(root);
    initAdminProductFormControls(root);
    initPurchaseOrderFormControls(root);
    initAiChatAssistant(root);
    initShopAiWidget(root);
    if (root === document) {
      initPaymentOptions();
    }
  };

  const body = document.body;
  const isAuthenticated = body.dataset.authenticated === 'true';
  const isAdminPage = body.dataset.pageRole === 'admin' || Boolean(document.querySelector('.admin-layout'));
  const authStateStorageKey = 'sweetcrumbs:auth-state';
  const adminScrollStorageKey = 'sweetcrumbs:admin-scroll-state';
  let refreshLiveSections = async () => {};
  let liveRefreshTimer = null;

  const syncAuthStateAcrossTabs = () => {
    if (!window.localStorage) return;

    if (isAuthenticated) {
      localStorage.setItem(authStateStorageKey, `authenticated:${Date.now()}`);
      return;
    }

    window.addEventListener('storage', (event) => {
      if (event.key !== authStateStorageKey || !event.newValue?.startsWith('authenticated:')) return;
      window.location.reload();
    });
    window.addEventListener('focus', () => {
      const authState = localStorage.getItem(authStateStorageKey) || '';
      if (authState.startsWith('authenticated:')) {
        window.location.reload();
      }
    });
  };

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

  const hasActiveEditor = () => {
    const activeElement = document.activeElement;
    if (!activeElement) return false;
    return ['INPUT', 'TEXTAREA', 'SELECT'].includes(activeElement.tagName) || activeElement.isContentEditable;
  };

  window.addEventListener('load', restoreAdminScrollState, { once: true });
  initializeUiBindings(document);
  syncAuthStateAcrossTabs();

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
  const scheduleFlashDismissal = (root = document) => {
    root.querySelectorAll?.('.flash-msg').forEach((flash) => {
      if (flash.dataset.dismissBound === 'true') return;
      flash.dataset.dismissBound = 'true';
      setTimeout(() => {
        flash.style.animation = 'slideIn 0.3s ease reverse';
        setTimeout(() => flash.remove(), 300);
      }, 4500);
    });
  };
  scheduleFlashDismissal(document);

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

  const adminScriptCache = new Set();

  const getAdminMain = () => document.querySelector('#admin-main, .admin-main');

  const isAdminNavigationLink = (event, link) => {
    if (!isAdminPage || !link) return false;
    if (event.defaultPrevented || event.button !== 0) return false;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
    if (link.target === '_blank' || link.hasAttribute('download')) return false;
    if (!link.closest('.admin-sidebar, .navbar--admin')) return false;

    const href = link.getAttribute('href');
    if (!href || href.startsWith('#')) return false;

    try {
      const url = new URL(href, window.location.href);
      return url.origin === window.location.origin && url.pathname.startsWith('/admin');
    } catch (error) {
      console.error('Unable to parse admin navigation URL.', error);
      return false;
    }
  };

  const loadExternalAdminScript = (script) => new Promise((resolve, reject) => {
    const src = script.src;
    if (!src || adminScriptCache.has(src)) {
      resolve();
      return;
    }

    const clone = document.createElement('script');
    clone.src = src;
    clone.async = false;
    if (script.type) clone.type = script.type;
    clone.onload = () => {
      adminScriptCache.add(src);
      resolve();
    };
    clone.onerror = () => reject(new Error(`Unable to load admin page script: ${src}`));
    document.body.appendChild(clone);
  });

  const runInlineAdminScript = (script) => {
    const code = script.textContent || '';
    if (!code.trim()) return;
    try {
      Function(code)();
    } catch (error) {
      console.error('Unable to run admin page script.', error);
    }
  };

  const executeAdminPageScripts = async (nextDocument, nextMain) => {
    const scripts = [
      ...nextMain.querySelectorAll('script'),
      ...nextDocument.querySelectorAll('#admin-page-scripts script'),
    ];

    for (const script of scripts) {
      if (script.src) {
        try {
          await loadExternalAdminScript(script);
        } catch (error) {
          console.error(error);
        }
      } else {
        runInlineAdminScript(script);
      }
    }
  };

  const stopAdminPageMedia = () => {
    getAdminMain()?.querySelectorAll('video').forEach((video) => {
      const stream = video.srcObject;
      if (!stream?.getTracks) return;
      stream.getTracks().forEach((track) => track.stop());
      video.srcObject = null;
    });
  };

  const updateAdminShellFromDocument = (nextDocument, targetUrl) => {
    const currentMain = getAdminMain();
    const nextMain = nextDocument.querySelector('#admin-main, .admin-main');
    if (!currentMain || !nextMain) return false;

    const nextTitle = nextDocument.querySelector('title')?.textContent;
    if (nextTitle) document.title = nextTitle;

    const currentFlash = document.querySelector('#flash-container');
    const nextFlash = nextDocument.querySelector('#flash-container');
    if (currentFlash && nextFlash) {
      currentFlash.innerHTML = nextFlash.innerHTML;
      scheduleFlashDismissal(currentFlash);
    }

    const currentNav = document.querySelector('.admin-nav');
    const nextNav = nextDocument.querySelector('.admin-nav');
    if (currentNav && nextNav) {
      currentNav.innerHTML = nextNav.innerHTML;
    }

    stopAdminPageMedia();
    currentMain.innerHTML = nextMain.innerHTML;
    currentMain.querySelectorAll('script').forEach((script) => script.remove());
    currentMain.dataset.currentUrl = targetUrl.toString();
    initializeUiBindings(currentMain);
    initCharts();
    setupLiveRefresh();
    scheduleFlashDismissal(currentMain);
    return true;
  };

  const loadAdminPage = async (href, {push = true, focusMain = true} = {}) => {
    const targetUrl = new URL(href, window.location.href);
    const currentUrl = new URL(window.location.href);
    const currentPath = `${currentUrl.pathname}${currentUrl.search}`;
    const targetPath = `${targetUrl.pathname}${targetUrl.search}`;
    const adminMain = getAdminMain();

    if (!adminMain) {
      window.location.href = targetUrl.toString();
      return;
    }

    if (targetUrl.origin !== window.location.origin || !targetUrl.pathname.startsWith('/admin')) {
      window.location.href = targetUrl.toString();
      return;
    }

    if (push && targetPath === currentPath) {
      adminSidebar?.classList.remove('open');
      if (focusMain) adminMain.focus({ preventScroll: true });
      return;
    }

    adminMain.classList.add('is-loading');
    adminMain.setAttribute('aria-busy', 'true');

    try {
      const response = await fetch(targetUrl.toString(), {
        headers: {
          'Accept': 'text/html',
          'X-Admin-Navigation': 'partial',
        },
        credentials: 'same-origin',
        cache: 'no-store',
      });
      if (!response.ok) throw new Error(`Admin navigation failed with status ${response.status}`);

      const html = await response.text();
      const nextDocument = new DOMParser().parseFromString(html, 'text/html');
      const nextMain = nextDocument.querySelector('#admin-main, .admin-main');
      if (!nextMain) {
        window.location.href = targetUrl.toString();
        return;
      }

      const swapped = updateAdminShellFromDocument(nextDocument, targetUrl);
      if (!swapped) {
        window.location.href = targetUrl.toString();
        return;
      }

      await executeAdminPageScripts(nextDocument, nextMain);
      document.dispatchEvent(new CustomEvent('sweetcrumbs:admin-page-loaded', {
        detail: { root: getAdminMain(), url: targetUrl.toString() },
      }));
      if (push) window.history.pushState({ adminPage: true }, '', targetUrl.toString());
      adminSidebar?.classList.remove('open');
      window.scrollTo({ top: 0, behavior: 'auto' });
      const updatedMain = getAdminMain();
      if (focusMain) updatedMain?.focus({ preventScroll: true });
    } catch (error) {
      console.error('Unable to load admin page without refresh.', error);
      window.location.href = targetUrl.toString();
    } finally {
      const updatedMain = getAdminMain();
      updatedMain?.classList.remove('is-loading');
      updatedMain?.removeAttribute('aria-busy');
    }
  };

  const initAdminPartialNavigation = () => {
    if (!isAdminPage || !window.fetch || !window.DOMParser || !window.history?.pushState) return;

    window.history.replaceState({ adminPage: true }, '', window.location.href);
    document.addEventListener('click', (event) => {
      const link = event.target.closest?.('a[href]');
      if (!isAdminNavigationLink(event, link)) return;
      event.preventDefault();
      loadAdminPage(link.href);
    });

    window.addEventListener('popstate', () => {
      loadAdminPage(window.location.href, { push: false, focusMain: false });
    });
  };
  initAdminPartialNavigation();

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
      freeDeliveryNote.innerHTML = freeDeliveryBannerHtml({
        subtotal: data.subtotal,
        threshold: data.delivery_threshold,
        unlocked: data.free_delivery_unlocked,
        count: data.count,
      });
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

    const subtotal = parseFloat(checkoutTotalEl.dataset.subtotal || 0);
    const memberDiscount = parseFloat(checkoutTotalEl.dataset.memberDiscount || 0);
    const deliveryCharge = parseFloat(checkoutTotalEl.dataset.deliveryCharge || 0);
    const gstRate = parseFloat(checkoutTotalEl.dataset.gstRate || 0);
    const fulfillmentCharge = pricingState.fulfillmentType === 'PICKUP' ? 0 : deliveryCharge;
    const taxableAmount = Math.max(0, subtotal - memberDiscount - pricingState.couponDiscount - pricingState.loyaltyDiscount);
    const taxAmount = Math.round((taxableAmount * gstRate / 100) * 100) / 100;
    const total = Math.max(0, taxableAmount + taxAmount + fulfillmentCharge);

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

    const taxValue = document.querySelector('#checkout-tax-value');
    const taxNote = document.querySelector('#checkout-tax-note');
    if (taxValue) {
      taxValue.textContent = formatCurrency(taxAmount);
      taxValue.dataset.gstAmount = String(taxAmount);
    }
    if (taxNote) {
      taxNote.textContent = `Calculated on taxable product value ${formatCurrency(taxableAmount)} before delivery and after product discounts.`;
    }

    const fulfillmentChargeLabel = document.querySelector('#checkout-fulfillment-charge-label');
    const fulfillmentChargeValue = document.querySelector('#checkout-fulfillment-charge-value');
    if (fulfillmentChargeLabel && fulfillmentChargeValue) {
      if (pricingState.fulfillmentType === 'PICKUP') {
        fulfillmentChargeLabel.textContent = 'Pickup';
        fulfillmentChargeValue.innerHTML = '<span style="color:var(--sage)">FREE</span>';
      } else {
        fulfillmentChargeLabel.textContent = 'Delivery';
        fulfillmentChargeValue.innerHTML = deliveryCharge > 0
          ? formatCurrency(deliveryCharge)
          : '<span style="color:var(--sage)">FREE</span>';
      }
    }

    const checkoutFreeDelivery = document.querySelector('#checkout-free-delivery-note');
    if (checkoutFreeDelivery) {
      if (pricingState.fulfillmentType === 'PICKUP') {
        checkoutFreeDelivery.innerHTML = '';
      } else {
        const deliveryThreshold = parseFloat(checkoutTotalEl.dataset.deliveryThreshold || 500);
        checkoutFreeDelivery.innerHTML = freeDeliveryBannerHtml({
          subtotal,
          threshold: deliveryThreshold,
          unlocked: subtotal >= deliveryThreshold,
          count: 1,
        });
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
  const miniCartFreeDelivery = document.querySelector('#mini-cart-free-delivery');
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
    if (miniCartFreeDelivery) {
      miniCartFreeDelivery.innerHTML = freeDeliveryBannerHtml({
        subtotal: data.subtotal,
        threshold: data.delivery_threshold,
        unlocked: data.free_delivery_unlocked,
        count: data.count,
      });
    }
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

  // ─── Charts (Admin) ──────────────────────────────
  initCharts();

  // ─── Delivery date min ───────────────────────────
  const deliveryDate = document.querySelector('#delivery_date');
  const pickupDate = document.querySelector('#pickup_date');
  if (deliveryDate) {
    deliveryDate.min = new Date().toISOString().split('T')[0];
  }
  if (pickupDate) {
    pickupDate.min = new Date().toISOString().split('T')[0];
  }

  const refreshDeliverySlots = () => {
    const deliverySlot = document.querySelector('#delivery_time_slot');
    if (!deliveryDate || !deliverySlot) return;

    const selectedDate = deliveryDate.value;
    const today = new Date().toISOString().split('T')[0];
    const now = new Date();
    let firstAvailableValue = '';

    deliverySlot.querySelectorAll('option').forEach((option) => {
      if (!option.value) return;
      let disabled = false;
      if (selectedDate === today) {
        const [hour, minute] = (option.dataset.slotStart || '').split(':').map(Number);
        if (Number.isFinite(hour) && Number.isFinite(minute)) {
          const slotStart = new Date(now);
          slotStart.setHours(hour, minute, 0, 0);
          disabled = slotStart <= now;
        }
      }
      option.disabled = disabled;
      option.hidden = disabled;
      if (!disabled && !firstAvailableValue) firstAvailableValue = option.value;
    });

    const selectedOption = deliverySlot.selectedOptions[0];
    if (selectedOption?.disabled) {
      deliverySlot.value = firstAvailableValue;
    }
  };

  deliveryDate?.addEventListener('change', refreshDeliverySlots);
  refreshDeliverySlots();

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
  const newAddressFields = document.querySelector('#checkout-new-address-fields');
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
    let selectedAddressCard = null;
    let suppressExactLocationReset = false;

    const isNewAddressCard = (card) => {
      const radio = card?.querySelector('input[type="radio"]');
      return !radio || !radio.value;
    };

    const setManualAddressFieldsEnabled = (enabled) => {
      newAddressFields?.classList.toggle('hidden', !enabled);
      Object.values(addressInputs).forEach((input) => {
        if (!input) return;
        input.disabled = !enabled;
      });
      newAddressFields?.querySelectorAll('input[type="checkbox"]').forEach((input) => {
        input.disabled = !enabled;
        if (!enabled) input.checked = false;
      });
      if (checkoutUseLocationButton) checkoutUseLocationButton.disabled = !enabled;
      newAddressFields?.querySelectorAll('[data-required-for-new-address="true"]').forEach((input) => {
        input.required = enabled;
      });
    };

    const clearManualAddressFields = () => {
      Object.values(addressInputs).forEach((input) => {
        if (input) input.value = '';
      });
    };

    const buildAddressQuery = () => {
      if (selectedAddressCard && !isNewAddressCard(selectedAddressCard)) {
        const parts = [
          selectedAddressCard.dataset.addressLine1 || '',
          selectedAddressCard.dataset.addressLine2 || '',
          selectedAddressCard.dataset.city || '',
          selectedAddressCard.dataset.pincode || '',
        ].map((part) => part.trim()).filter(Boolean);
        return parts.join(', ');
      }
      const parts = [
        addressInputs.addressLine1?.value || '',
        addressInputs.addressLine2?.value || '',
        addressInputs.city?.value || '',
        addressInputs.pincode?.value || '',
      ].map((part) => part.trim()).filter(Boolean);
      return parts.join(', ');
    };

    const getExactLocation = () => {
      if (selectedAddressCard && !isNewAddressCard(selectedAddressCard)) {
        const rawLatitude = selectedAddressCard.dataset.latitude || '';
        const rawLongitude = selectedAddressCard.dataset.longitude || '';
        if (!rawLatitude || !rawLongitude) return null;
        const latitude = Number(rawLatitude);
        const longitude = Number(rawLongitude);
        if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
        return {
          latitude: Number(latitude.toFixed(7)),
          longitude: Number(longitude.toFixed(7)),
        };
      }
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
      const manualAddress = isNewAddressCard(card);
      selectedAddressCard = card;
      setManualAddressFieldsEnabled(manualAddress);
      if (!manualAddress) {
        clearManualAddressFields();
        updateCheckoutAddressMap();
        return;
      }

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

  const badgeClassForOrderStatus = (status) => {
    if (status === 'DELIVERED') return 'badge-green';
    if (status === 'CANCELLED') return 'badge-red';
    if (status === 'OUT_FOR_DELIVERY') return 'badge-blue';
    if (status === 'ON_HOLD') return 'badge-orange';
    return 'badge-brown';
  };

  const badgeClassForStock = (stock) => {
    if (stock <= 0) return 'badge-red';
    if (stock <= 5) return 'badge-orange';
    return 'badge-green';
  };

  const stockLabel = (stock, compact = false) => {
    if (stock <= 0) return compact ? 'Out of Stock' : 'Out of Stock';
    if (stock <= 5) return compact ? `Only ${stock} left!` : 'Low Stock';
    return compact ? 'In Stock' : 'OK';
  };

  const setOrderStatusBadge = (badge, status) => {
    if (!badge || !status) return;
    const prefix = badge.textContent.trim().startsWith('Current:') ? 'Current: ' : '';
    badge.className = `badge ${badgeClassForOrderStatus(status)}`;
    badge.textContent = `${prefix}${status.replace(/_/g, ' ')}`;
  };

  const updateVisibleOrderStatus = (orderId, status) => {
    if (!orderId || !status) return;
    const normalizedStatus = String(status).toUpperCase();
    document.querySelectorAll(`[data-order-status="${orderId}"]`).forEach((badge) => {
      setOrderStatusBadge(badge, normalizedStatus);
      pulseRealtimeElement(badge);
    });
    document.querySelectorAll(`[data-order-id="${orderId}"]`).forEach((element) => {
      pulseRealtimeElement(element);
    });
    document.querySelectorAll('[data-tracker-status]').forEach((step) => {
      const trackerStatus = (step.dataset.trackerStatus || '').toUpperCase();
      const sequence = ['PLACED', 'PREPARING', 'PACKED', 'OUT_FOR_DELIVERY', 'DELIVERED'];
      const currentIndex = sequence.indexOf(normalizedStatus);
      const stepIndex = sequence.indexOf(trackerStatus);
      step.classList.toggle('active', trackerStatus === normalizedStatus);
      step.classList.toggle(
        'completed',
        currentIndex >= 0 && stepIndex >= 0 && stepIndex < currentIndex
      );
    });
    document.dispatchEvent(new CustomEvent('sweetcrumbs:order-status-updated', {
      detail: { orderId, status: normalizedStatus },
    }));
  };

  const incrementRealtimeCounter = (name) => {
    document.querySelectorAll(`[data-rt-counter="${name}"]`).forEach((counter) => {
      const current = Number((counter.textContent || '').replace(/[^\d.-]/g, '')) || 0;
      counter.textContent = String(current + 1);
      pulseRealtimeElement(counter);
    });
  };

  const makeCell = (text) => {
    const cell = document.createElement('td');
    cell.textContent = text;
    return cell;
  };

  const pulseRealtimeElement = (element) => {
    if (!element) return;
    element.classList.remove('rt-highlight');
    void element.offsetWidth;
    element.classList.add('rt-highlight');
    window.setTimeout(() => element.classList.remove('rt-highlight'), 1800);
  };

  const makeTextElement = (tagName, text, className = '') => {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    element.textContent = text || '';
    return element;
  };

  const makeLink = (href, text, className = '') => {
    const link = document.createElement('a');
    link.href = href || '#';
    link.textContent = text;
    if (className) link.className = className;
    return link;
  };

  const appendSupportMessage = (payload) => {
    if (!payload?.customer_id || !payload?.message_id) return;
    document.querySelectorAll('[data-support-message-list]').forEach((list) => {
      if (String(list.dataset.supportCustomerId || '') !== String(payload.customer_id)) return;
      if (list.querySelector(`[data-support-message-id="${payload.message_id}"]`)) return;

      list.querySelectorAll('.support-empty-state').forEach((state) => state.remove());
      const currentUserId = String(list.dataset.currentUserId || '');
      const isSent = String(payload.sender_id || '') === currentUserId;
      const wrapper = document.createElement('div');
      wrapper.dataset.supportMessageId = payload.message_id;

      const bubble = document.createElement('div');
      bubble.className = `msg-bubble ${isSent ? 'sent' : 'received'}`;
      if (!isSent) {
        bubble.appendChild(makeTextElement('div', payload.sender_name || 'Support', 'support-message-author'));
      }
      bubble.appendChild(document.createTextNode(payload.content || ''));
      const sentAt = payload.sent_at ? new Date(payload.sent_at) : new Date();
      bubble.appendChild(makeTextElement(
        'div',
        sentAt.toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }),
        'msg-time',
      ));
      wrapper.appendChild(bubble);
      list.appendChild(wrapper);
      list.scrollTop = list.scrollHeight;
      pulseRealtimeElement(wrapper);
    });

    document.querySelectorAll(`[data-support-thread="${payload.customer_id}"]`).forEach((thread) => {
      pulseRealtimeElement(thread);
    });
  };

  const prependAdminOrder = (payload) => {
    if (!payload?.order_id) return;
    document.querySelectorAll('[data-admin-orders-table]').forEach((tbody) => {
      if (tbody.querySelector(`[data-order-id="${payload.order_id}"]`)) return;
      tbody.querySelector('td[colspan]')?.closest('tr')?.remove();

      const row = document.createElement('tr');
      row.dataset.orderId = payload.order_id;

      const linkCell = document.createElement('td');
      const link = document.createElement('a');
      link.href = payload.detail_url || `/admin/orders/${payload.order_id}`;
      link.style.fontWeight = '600';
      link.style.color = 'var(--brown)';
      link.textContent = `#${payload.order_number || payload.order_id}`;
      linkCell.appendChild(link);
      row.appendChild(linkCell);

      row.appendChild(makeCell(payload.customer_name || 'Customer'));
      row.appendChild(makeCell(payload.item_summary || 'New order'));

      const totalCell = makeCell(formatCurrency(payload.total || 0));
      totalCell.style.fontWeight = '600';
      totalCell.style.color = 'var(--caramel)';
      row.appendChild(totalCell);

      if (tbody.dataset.adminOrdersTable === 'orders') {
        const paymentCell = document.createElement('td');
        const paymentBadge = document.createElement('span');
        paymentBadge.className = 'badge badge-orange';
        paymentBadge.textContent = 'PENDING';
        paymentCell.appendChild(paymentBadge);
        row.appendChild(paymentCell);
      }

      const statusCell = document.createElement('td');
      const statusBadge = document.createElement('span');
      statusBadge.dataset.orderStatus = payload.order_id;
      setOrderStatusBadge(statusBadge, payload.status || 'PLACED');
      statusCell.appendChild(statusBadge);
      row.appendChild(statusCell);

      const date = payload.timestamp ? new Date(payload.timestamp) : new Date();
      row.appendChild(makeCell(date.toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })));

      const actionCell = document.createElement('td');
      const action = document.createElement('a');
      action.href = payload.detail_url || `/admin/orders/${payload.order_id}`;
      action.className = 'btn btn-ghost btn-sm';
      action.textContent = 'View';
      actionCell.appendChild(action);
      row.appendChild(actionCell);

      tbody.prepend(row);
      pulseRealtimeElement(row);
    });

    incrementRealtimeCounter('total-orders');
    incrementRealtimeCounter('pending-orders');
    incrementRealtimeCounter('today-orders');
  };

  const prependDeliveryAssignment = (payload) => {
    if (!payload?.order_id) return;

    const liveRegion = document.querySelector('#delivery-dashboard-live');
    if (!liveRegion) return;

    liveRegion.querySelectorAll('.empty-state').forEach((state) => state.remove());

    let list = liveRegion.querySelector('[data-delivery-assignment-list]');
    if (!list) {
      list = document.createElement('div');
      list.className = 'delivery-assigned-list';
      list.dataset.deliveryAssignmentList = 'active';
      liveRegion.prepend(list);
    }

    if (list.querySelector(`[data-order-id="${payload.order_id}"]`)) return;

    const card = document.createElement('article');
    card.className = 'ops-order-card';
    card.dataset.orderId = payload.order_id;

    const head = document.createElement('div');
    head.className = 'ops-order-card-head';

    const titleWrap = document.createElement('div');
    titleWrap.appendChild(makeTextElement('div', `Order #${payload.order_number || payload.order_id}`, 'ops-order-kicker'));
    titleWrap.appendChild(makeTextElement('h3', payload.customer_name || 'Customer'));
    head.appendChild(titleWrap);

    const meta = document.createElement('div');
    meta.className = 'ops-order-head-meta';
    const badge = makeTextElement('span', (payload.status || 'PLACED').replace(/_/g, ' '), `badge ${badgeClassForOrderStatus(payload.status || 'PLACED')}`);
    badge.dataset.orderStatus = payload.order_id;
    meta.appendChild(badge);
    meta.appendChild(makeTextElement('strong', formatCurrency(payload.total || 0)));
    head.appendChild(meta);
    card.appendChild(head);

    const metaRow = document.createElement('div');
    metaRow.className = 'ops-order-meta-row';
    const phoneLink = makeLink(`tel:${payload.phone || ''}`, payload.phone || 'No phone');
    const phoneWrap = document.createElement('span');
    phoneWrap.textContent = 'Phone: ';
    phoneWrap.appendChild(phoneLink);
    metaRow.appendChild(phoneWrap);
    metaRow.appendChild(makeTextElement('span', payload.items_summary || payload.item_summary || 'New assignment'));
    card.appendChild(metaRow);

    if (payload.delivery_address) {
      card.appendChild(makeTextElement('p', payload.delivery_address, 'ops-order-address'));
    }

    if (payload.special_instructions) {
      card.appendChild(makeTextElement('p', payload.special_instructions, 'ops-order-note'));
    }

    const actions = document.createElement('div');
    actions.className = 'ops-order-actions';
    actions.appendChild(makeLink(`tel:${payload.phone || ''}`, 'Call Customer', 'btn btn-outline btn-sm'));
    actions.appendChild(makeLink(payload.detail_url || `/delivery/order/${payload.order_id}`, 'View Details', 'btn btn-ghost btn-sm'));
    card.appendChild(actions);

    list.prepend(card);
    incrementRealtimeCounter('assigned-deliveries');
    pulseRealtimeElement(card);
  };

  const updateStockIndicators = (payload) => {
    const variantId = payload?.variant_id;
    const newStock = Number(payload?.new_stock);
    if (!variantId || Number.isNaN(newStock)) return;

    document.querySelectorAll(`[data-stock-value="${variantId}"]`).forEach((valueEl) => {
      valueEl.textContent = String(newStock);
      valueEl.style.color = newStock <= 0
        ? 'var(--dusty-rose)'
        : newStock <= 5 ? 'var(--caramel)' : 'var(--sage)';
    });

    document.querySelectorAll(`[data-stock-status="${variantId}"]`).forEach((badge) => {
      badge.className = `badge ${badgeClassForStock(newStock)}`;
      badge.textContent = stockLabel(newStock);
    });

    document.querySelectorAll(`[data-stock-input="${variantId}"]`).forEach((input) => {
      input.value = String(newStock);
    });

    document.querySelectorAll(`[data-pos-stock-label="${variantId}"]`).forEach((label) => {
      label.className = 'pos-product-stock';
      label.textContent = newStock <= 0
        ? 'Out of Stock'
        : newStock <= 5 ? `Only ${newStock} left` : `${newStock} in stock`;
    });

    document.querySelectorAll(`[data-pos-add][data-variant-id="${variantId}"]`).forEach((button) => {
      button.dataset.stock = String(newStock);
      button.disabled = newStock <= 0;
      button.setAttribute('aria-disabled', newStock <= 0 ? 'true' : 'false');
      button.closest('[data-pos-product-card]')?.classList.toggle('is-out-of-stock', newStock <= 0);
    });

    document.querySelectorAll(`.variant-btn[data-variant-id="${variantId}"]`).forEach((button) => {
      button.dataset.stock = String(newStock);
      button.disabled = newStock <= 0;
      button.style.opacity = newStock <= 0 ? '0.5' : '';
      button.style.cursor = newStock <= 0 ? 'not-allowed' : '';
      if (button.classList.contains('active')) {
        const stockBadge = document.querySelector(`[data-product-stock-badge="${payload.product_id}"], .live-stock-badge`);
        if (stockBadge) {
          stockBadge.className = `badge ${badgeClassForStock(newStock)} live-stock-badge`;
          stockBadge.textContent = stockLabel(newStock, true);
        }
        const qtyInput = document.querySelector('.qty-input');
        if (qtyInput) qtyInput.max = String(Math.max(newStock, 0));
      }
    });
  };

  // ─── Live refresh for order/admin pages ─────────
  const setupLiveRefresh = () => {
    if (liveRefreshTimer) {
      window.clearInterval(liveRefreshTimer);
      liveRefreshTimer = null;
    }

    refreshLiveSections = async () => {};
    const liveRefreshTarget = document.querySelector('[data-live-refresh]');
    if (!liveRefreshTarget) return;

    const intervalMs = Number(liveRefreshTarget.dataset.liveRefresh || 15000);
    const liveRefreshSource = liveRefreshTarget.dataset.liveRefreshSource || '';
    let isReloading = false;
    let isFetching = false;

    if (liveRefreshSource) {
      refreshLiveSections = async ({respectEditors = false} = {}) => {
        if (document.hidden || isFetching || (respectEditors && hasActiveEditor())) return;
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
      };

      liveRefreshTimer = window.setInterval(async () => {
        refreshLiveSections({respectEditors: true});
      }, intervalMs);
      return;
    }

    liveRefreshTimer = window.setInterval(() => {
      if (document.hidden || hasActiveEditor() || isReloading) return;
      isReloading = true;
      saveAdminScrollState();

      if (isAdminPage) {
        loadAdminPage(window.location.href, { push: false, focusMain: false })
          .finally(() => { isReloading = false; });
        return;
      }

      window.location.reload();
    }, intervalMs);
  };
  setupLiveRefresh();

  const initRealtimeSocket = () => {
    const portal = document.body.dataset.pageRole;
    if (!window.io || !['customer', 'admin', 'delivery'].includes(portal)) return;
    if (window.sweetCrumbsSocket) return;

    const socket = window.io({
      query: { portal },
      transports: ['websocket', 'polling'],
      reconnection: true,
      reconnectionAttempts: Infinity,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 60000,
      randomizationFactor: 0.2,
    });
    window.sweetCrumbsSocket = socket;

    socket.on('new_order', (payload) => {
      if (portal === 'admin') {
        prependAdminOrder(payload);
        if (document.querySelector('[data-socket-room="kds"]')) {
          window.location.reload();
          return;
        }
        refreshLiveSections({respectEditors: true});
      }
    });

    socket.on('delivery_assignment', (payload) => {
      if (portal === 'delivery') {
        prependDeliveryAssignment(payload);
      }
    });

    socket.on('order_status_updated', (payload) => {
      updateVisibleOrderStatus(payload?.order_id, payload?.new_status || payload?.status);
      if (document.querySelector('[data-socket-room="kds"]')) {
        window.location.reload();
        return;
      }
      refreshLiveSections({respectEditors: true});
    });

    socket.on('stock_updated', updateStockIndicators);
    socket.on('support_message', appendSupportMessage);
    socket.on('kds_refresh', () => {
      if (document.querySelector('[data-socket-room="kds"]')) window.location.reload();
    });
    socket.on('order_updated', () => {
      if (document.querySelector('[data-socket-room="kds"]')) {
        window.location.reload();
        return;
      }
      refreshLiveSections({respectEditors: true});
    });
  };

  initRealtimeSocket();

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

/**
 * ShopSmart AI — Direct Search (No AI needed)
 */
const Search = {
    inputEl: null,
    btnEl: null,
    resultsEl: null,
    statusEl: null,
    isSearching: false,

    init() {
        this.inputEl = document.getElementById('search-input');
        this.btnEl = document.getElementById('btn-search');
        this.resultsEl = document.getElementById('search-results');
        this.statusEl = document.getElementById('search-status');

        if (!this.btnEl) return;

        this.compareBtnEl = document.getElementById('btn-compare');
        this.btnEl.addEventListener('click', () => this.doSearch());
        if (this.compareBtnEl) {
            this.compareBtnEl.addEventListener('click', () => this.doCompare());
        }
        this.inputEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.doSearch();
        });

        // Tag buttons
        document.querySelectorAll('.search-tag').forEach(tag => {
            tag.addEventListener('click', () => {
                this.inputEl.value = tag.dataset.q;
                this.doSearch();
            });
        });
    },

    async doSearch() {
        const query = this.inputEl.value.trim();
        if (!query || this.isSearching) return;

        this.isSearching = true;
        this.btnEl.disabled = true;
        this.btnEl.textContent = 'Searching...';

        // Show loading
        this.statusEl.style.display = 'flex';
        this.statusEl.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Searching Amazon.in, Flipkart, Croma, Reliance Digital, Vijay Sales, Tata CLiQ, Myntra, and Snapdeal...';

        // Show skeleton cards
        this.resultsEl.innerHTML = Array(6).fill('<div class="product-skeleton"></div>').join('');

        try {
            const data = await API.get(`/api/search?q=${encodeURIComponent(query)}`);

            if (data.error) {
                this.statusEl.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${data.error}`;
                this.resultsEl.innerHTML = '';
            } else {
                this.renderResults(data, query);
            }
        } catch (err) {
            this.statusEl.innerHTML = '<i class="fas fa-exclamation-circle"></i> Server connection error';
            this.resultsEl.innerHTML = '';
        }

        this.isSearching = false;
        this.btnEl.disabled = false;
        this.btnEl.textContent = 'Search';
    },

    renderResults(data, query) {
        const results = data.results || [];
        const sources = data.sources_found || [];

        // Status bar
        if (results.length === 0) {
            this.statusEl.innerHTML = `<i class="fas fa-info-circle"></i> No results found for "${query}". Try another search term.`;
            this.resultsEl.innerHTML = '';
            return;
        }

        let statusHtml = `<i class="fas fa-check-circle"></i> Found <strong>${results.length}</strong> results for "${query}"`;
        if (sources.length > 0) {
            statusHtml += ` &mdash; Stores: ${sources.join(', ')}`;
        }
        this.statusEl.innerHTML = statusHtml;

        // Keep results around so the track action can read them by index.
        this._results = results;

        // Render product cards
        this.resultsEl.innerHTML = results.map((r, i) => {
            const source = r.source || 'Web';
            const badgeClass = this._sourceBadgeClass(source);
            const snippet = r.snippet
                ? `<div class="product-snippet">${r.snippet}</div>`
                : '';
            const viewBtn = r.url
                ? `<a href="${r.url}" target="_blank" rel="noopener" class="btn-visit"><i class="fas fa-external-link-alt"></i> View at ${source}</a>`
                : '';
            const priceBtn = r.url
                ? `<button class="btn-check-price" onclick="Search.fetchPrice('${r.url}', ${i})" id="price-btn-${i}"><i class="fas fa-tag"></i> Check price</button>`
                : '';

            return `
                <div class="product-card">
                    <div class="product-header">
                        <span class="product-source-badge ${badgeClass}">${source}</span>
                        <div class="product-name">${r.product_name || 'Product'}</div>
                    </div>
                    ${snippet}
                    <div class="product-price-display" id="price-display-${i}"></div>
                    <div class="product-footer">
                        <div class="product-actions">
                            ${priceBtn}
                            ${viewBtn}
                        </div>
                        <div class="track-row">
                            <input type="number" min="0" step="1000" class="track-target-input"
                                   id="track-target-${i}" placeholder="Target price (₹) — optional">
                            <button class="btn-track" id="track-btn-${i}" onclick="Search.trackProduct(${i})">
                                <i class="fas fa-bell"></i> Track
                            </button>
                        </div>
                    </div>
                </div>`;
        }).join('');
    },

    async doCompare() {
        const query = this.inputEl.value.trim();
        if (!query || this.isSearching) return;

        this.isSearching = true;
        if (this.compareBtnEl) this.compareBtnEl.disabled = true;
        this.btnEl.disabled = true;

        this.statusEl.style.display = 'flex';
        this.statusEl.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Comparing prices across stores (this may take a few seconds)...';
        this.resultsEl.innerHTML = Array(4).fill('<div class="product-skeleton"></div>').join('');

        try {
            const data = await API.compare(query);
            if (data.error) {
                this.statusEl.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${data.error}`;
                this.resultsEl.innerHTML = '';
            } else {
                this.renderComparison(data, query);
            }
        } catch (err) {
            console.error('Compare error:', err);
            this.statusEl.innerHTML = '<i class="fas fa-exclamation-circle"></i> Server connection error';
            this.resultsEl.innerHTML = '';
        }

        this.isSearching = false;
        if (this.compareBtnEl) this.compareBtnEl.disabled = false;
        this.btnEl.disabled = false;
    },

    renderComparison(data, query) {
        const offers = data.offers || [];
        if (offers.length === 0) {
            this.statusEl.innerHTML = `<i class="fas fa-info-circle"></i> No products found to compare for "${query}".`;
            this.resultsEl.innerHTML = '';
            return;
        }

        const cheapest = data.cheapest_source;
        let statusHtml = `<i class="fas fa-balance-scale"></i> Compare <strong>${offers.length}</strong> stores for "${query}"`;
        if (data.priced_count > 0 && cheapest) {
            statusHtml += ` &mdash; Lowest price: <strong>${cheapest}</strong>`;
        } else {
            statusHtml += ' &mdash; could not retrieve prices from any store (the sites may block price extraction).';
        }
        this.statusEl.innerHTML = statusHtml;

        const rows = offers.map(o => {
            const badge = this._sourceBadgeClass(o.source);
            const priceCell = o.price != null
                ? `<span class="cmp-price">${formatINR(o.price)}</span>`
                : '<span class="cmp-price no-price">—</span>';
            const best = o.is_cheapest
                ? '<span class="cmp-best"><i class="fas fa-crown"></i> Lowest price</span>' : '';
            const link = o.url
                ? `<a href="${o.url}" target="_blank" rel="noopener" class="cmp-link"><i class="fas fa-external-link-alt"></i> View</a>`
                : '';
            return `
                <div class="cmp-row ${o.is_cheapest ? 'cheapest' : ''}">
                    <span class="product-source-badge ${badge}">${o.source}</span>
                    <span class="cmp-name">${o.product_name || 'Product'}</span>
                    ${priceCell}
                    ${best}
                    ${link}
                </div>`;
        }).join('');

        this.resultsEl.innerHTML = `<div class="compare-table">${rows}</div>`;
    },

    async trackProduct(index) {
        const r = (this._results || [])[index];
        if (!r) return;
        const btn = document.getElementById(`track-btn-${index}`);
        const targetEl = document.getElementById(`track-target-${index}`);
        const targetRaw = targetEl ? targetEl.value.trim() : '';

        // Reuse a price already fetched for this card, if any.
        const displayEl = document.getElementById(`price-display-${index}`);
        let currentPrice = null;
        if (displayEl) {
            const m = displayEl.textContent.replace(/[^\d]/g, '');
            if (m) currentPrice = Number(m);
        }

        if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...'; }

        try {
            const payload = {
                name: r.product_name || 'Product',
                url: r.url || null,
                source: r.source || null,
            };
            if (currentPrice) payload.current_price = currentPrice;
            if (targetRaw) payload.target_price = Number(targetRaw);

            const data = await API.post('/api/track', payload);
            if (data.success) {
                if (btn) { btn.innerHTML = '<i class="fas fa-check"></i> Tracked'; btn.classList.add('tracked'); }
                if (typeof Dashboard !== 'undefined') Dashboard.refresh();
            } else {
                if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-bell"></i> Track'; }
                alert(data.error || 'Could not track this product.');
            }
        } catch (e) {
            console.error('Track error:', e);
            if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-bell"></i> Track'; }
            alert('Connection error while tracking product.');
        }
    },

    async fetchPrice(url, index) {
        const btn = document.getElementById(`price-btn-${index}`);
        const display = document.getElementById(`price-display-${index}`);
        if (!btn || !display) return;

        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Fetching price...';

        try {
            const data = await API.post('/api/scrape-price', { url });

            if (data.price) {
                display.innerHTML = `<span class="product-price">${formatINR(data.price)}</span>`;
                btn.style.display = 'none';
            } else {
                display.innerHTML = '<span class="product-price no-price">Could not retrieve the price. View it on the store website.</span>';
                btn.style.display = 'none';
            }
        } catch (err) {
            display.innerHTML = '<span class="product-price no-price">Connection error</span>';
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-tag"></i> Try again';
        }
    },

    _sourceBadgeClass(source) {
        const map = {
            'Amazon India': 'amazon-india', 'Flipkart': 'flipkart',
            'Croma': 'croma', 'Reliance Digital': 'reliance-digital',
            'Vijay Sales': 'vijay-sales', 'Tata CLiQ': 'tata-cliq',
            'Myntra': 'myntra', 'Snapdeal': 'snapdeal',
        };
        return map[source] || 'web';
    }
};

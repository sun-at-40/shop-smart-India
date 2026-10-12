/**
 * ShopSmart AI — Wishlist & Budget Planner
 */
const Planner = {
    _categories: [],

    _esc(s) {
        return String(s ?? '').replace(/[&<>"']/g,
            (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    },

    _showError(id, msg) {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = msg || '';
        el.style.display = msg ? 'block' : 'none';
    },

    init() {
        const on = (id, fn) => {
            const el = document.getElementById(id);
            if (el) el.addEventListener('click', fn);
        };
        on('btn-add-wish', () => this.addItem());
        on('btn-set-budget', () => this.setBudget());

        // One delegated handler for all item / budget buttons.
        const view = document.getElementById('view-planner');
        if (view) view.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-act]');
            if (btn) this.act(btn.dataset.act, btn.dataset.id);
        });
    },

    async load() {
        try {
            const data = await API.getPlanner();
            if (!data || data.error) return;
            this._categories = data.categories || [];
            this._fillCategories();
            this._renderStats(data.summary.totals);
            this._renderBudgets(data.summary.categories);
            this._renderItems(data.items);
        } catch (e) {
            console.warn('Planner.load failed', e);
        }
    },

    _fillCategories() {
        const opts = this._categories.map((c) => `<option>${this._esc(c)}</option>`).join('');
        ['budget-category', 'wish-category'].forEach((id) => {
            const el = document.getElementById(id);
            if (el && !el.options.length) el.innerHTML = opts;
        });
    },

    _renderStats(t) {
        const stat = (label, val, cls = '') =>
            `<div class="planner-stat ${cls}"><span>${label}</span><strong>${formatINR(val)}</strong></div>`;
        document.getElementById('planner-stats').innerHTML =
            stat('Total monthly budget', t.budget) +
            stat('Spent this month', t.spent_this_month) +
            stat('Planned (open wishlist)', t.planned) +
            stat('Saved by waiting for deals', t.saved, 'good');
    },

    _renderBudgets(cats) {
        const rows = cats.filter((c) => c.budget);
        const box = document.getElementById('planner-budgets');
        if (!rows.length) {
            box.innerHTML = '<p class="settings-hint">No budgets yet. Set one below.</p>';
            return;
        }
        box.innerHTML = rows.map((c) => {
            const pct = Math.min(100, c.used_pct);
            const left = c.remaining >= 0
                ? `${formatINR(c.remaining)} left`
                : `${formatINR(-c.remaining)} over budget`;
            const warn = c.planned_over > 0 && c.status !== 'over'
                ? ` · wishlist would exceed by ${formatINR(c.planned_over)}` : '';
            return `<div class="budget-row">
                <div class="budget-head">
                    <span><strong>${this._esc(c.category)}</strong>
                        <small>${formatINR(c.spent)} of ${formatINR(c.budget)}</small></span>
                    <span><small>${left}${warn}</small>
                        <button class="btn-icon" title="Remove budget" data-act="del-budget"
                            data-id="${this._esc(c.category)}"><i class="fas fa-times"></i></button></span>
                </div>
                <div class="budget-bar ${c.status}"><div style="width:${pct}%"></div></div>
            </div>`;
        }).join('');
    },

    _renderItems(items) {
        const box = document.getElementById('planner-items');
        if (!items.length) {
            box.innerHTML = '<p class="settings-hint">Your wishlist is empty. Add something you want to buy.</p>';
            return;
        }
        const rank = { high: 0, medium: 1, low: 2 };
        const sorted = [...items].sort((a, b) =>
            (a.status === 'purchased') - (b.status === 'purchased') || rank[a.priority] - rank[b.priority]);
        box.innerHTML = sorted.map((i) => {
            const done = i.status === 'purchased';
            const link = i.url
                ? `<a href="${this._esc(i.url)}" target="_blank" rel="noopener noreferrer">${this._esc(i.name)}</a>`
                : this._esc(i.name);
            const meta = [
                this._esc(i.category),
                done ? `paid ${formatINR(i.purchased_price)}`
                     : `target ${i.target_price ? formatINR(i.target_price) : '—'}` +
                       (i.est_price ? ` · now ${formatINR(i.est_price)}` : ''),
                `<span class="pri-${i.priority}">${i.priority} priority</span>`,
                i.tracked_product_id ? 'tracking price' : '',
            ].filter(Boolean).join(' · ');
            const actions = done
                ? `<button data-act="reopen" data-id="${i.id}">Undo purchase</button>`
                : `<button data-act="buy" data-id="${i.id}"><i class="fas fa-check"></i> Bought</button>` +
                  (i.tracked_product_id ? '' : `<button data-act="track" data-id="${i.id}"><i class="fas fa-chart-line"></i> Track price</button>`);
            return `<div class="wish-item ${done ? 'purchased' : ''}">
                <div class="wish-main"><div class="wish-name">${link}</div><div class="wish-meta">${meta}</div></div>
                <div class="wish-actions">${actions}
                    <button data-act="del" data-id="${i.id}" title="Delete"><i class="fas fa-trash"></i></button></div>
            </div>`;
        }).join('');
    },

    _num(id) {
        const v = document.getElementById(id).value;
        return v === '' ? null : Number(v);
    },

    async addItem() {
        this._showError('wish-error');
        const payload = {
            name: document.getElementById('wish-name').value,
            category: document.getElementById('wish-category').value,
            est_price: this._num('wish-est'),
            target_price: this._num('wish-target'),
            priority: document.getElementById('wish-priority').value,
            url: document.getElementById('wish-url').value,
        };
        const data = await API.addWish(payload);
        if (data.error) return this._showError('wish-error', data.error);
        ['wish-name', 'wish-est', 'wish-target', 'wish-url'].forEach((id) => {
            document.getElementById(id).value = '';
        });
        this.load();
    },

    async setBudget() {
        this._showError('budget-error');
        const data = await API.setBudget(
            document.getElementById('budget-category').value, this._num('budget-limit'));
        if (data.error) return this._showError('budget-error', data.error);
        document.getElementById('budget-limit').value = '';
        this.load();
    },

    async act(action, id) {
        let res;
        if (action === 'buy') {
            const paid = prompt('Price you paid (₹)? Leave blank to use your target price.');
            if (paid === null) return;
            res = await API.purchaseWish(id, paid.trim() === '' ? null : Number(paid));
        } else if (action === 'reopen') res = await API.reopenWish(id);
        else if (action === 'track') res = await API.trackWish(id);
        else if (action === 'del') {
            if (!confirm('Delete this wishlist item?')) return;
            res = await API.deleteWish(id);
        } else if (action === 'del-budget') res = await API.deleteBudget(id);
        if (res && res.error) alert(res.error);
        this.load();
    },
};

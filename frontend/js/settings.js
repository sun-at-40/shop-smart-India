/**
 * ShopSmart AI — Settings (account + notification channels)
 */
const Settings = {
    _channels: { telegram: false, email: false },

    init() {
        const saveBtn = document.getElementById('btn-save-settings');
        if (saveBtn) saveBtn.addEventListener('click', () => this.save());
        const testBtn = document.getElementById('btn-test-alert');
        if (testBtn) testBtn.addEventListener('click', () => this.sendTest());
        const clearBtn = document.getElementById('btn-clear-outbox');
        if (clearBtn) clearBtn.addEventListener('click', async () => {
            await API.clearOutbox();
            this.loadOutbox();
        });
        // Server channel availability (whether the deployment has Telegram/SMTP configured).
        this._loadChannelStatus();
    },

    _setMsg(kind, msg) {
        const errEl = document.getElementById('settings-error');
        const okEl = document.getElementById('settings-success');
        if (errEl) errEl.style.display = 'none';
        if (okEl) okEl.style.display = 'none';
        const el = kind === 'error' ? errEl : okEl;
        if (el) {
            el.textContent = msg || '';
            el.style.display = msg ? 'block' : 'none';
        }
    },

    async _loadChannelStatus() {
        try {
            const health = await API.healthCheck();
            this._channels = health.channels || { telegram: false, email: false };
        } catch (e) {
            console.warn('Settings: health check failed', e);
        }
        this._renderChannelStatus();
    },

    _renderChannelStatus() {
        const box = document.getElementById('settings-channel-status');
        if (!box) return;
        const chip = (ok, label) =>
            `<span class="channel-chip ${ok ? 'on' : 'off'}">
                <i class="fas fa-${ok ? 'check-circle' : 'times-circle'}"></i> ${label} ${ok ? 'ready' : 'not configured'}
             </span>`;
        box.innerHTML =
            chip(this._channels.email, 'Email (SMTP)') +
            chip(this._channels.telegram, 'Telegram bot');

        // If the server has no Telegram bot token, the chat id field can't do anything.
        const tgField = document.getElementById('settings-telegram');
        if (tgField && !this._channels.telegram) {
            tgField.disabled = true;
            tgField.placeholder = 'The server has not configured TELEGRAM_BOT_TOKEN';
        }
        const emailStatus = document.getElementById('settings-email-status');
        if (emailStatus && !this._channels.email) {
            emailStatus.textContent = 'The server has not configured SMTP, so enabling this will not send emails.';
        }
    },

    async sendTest() {
        this._setMsg();
        try {
            const data = await API.sendTestAlert();
            if (data && data.error) return this._setMsg('error', data.error);
            const r = (data && data.result) || {};
            const sent = [r.email && 'email', r.telegram && 'Telegram'].filter(Boolean);
            if (sent.length) {
                this._setMsg('success', `Test alert ${data.simulated ? 'simulated' : 'sent'} via ${sent.join(' and ')}.`);
            } else {
                this._setMsg('error', 'No channel delivered the alert. Enable email or save a Telegram chat ID first.');
            }
            this.loadOutbox();
        } catch (e) {
            this._setMsg('error', 'Connection error while sending the test alert.');
        }
    },

    async loadOutbox() {
        const card = document.getElementById('outbox-card');
        const list = document.getElementById('outbox-list');
        if (!card || !list) return;
        try {
            const data = await API.getOutbox();
            if (!data || !data.simulated) { card.style.display = 'none'; return; }
            card.style.display = '';
            const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
                (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
            const msgs = data.messages || [];
            list.innerHTML = msgs.length ? msgs.map((m) => `
                <div class="settings-row" style="display:block">
                    <div><i class="${m.channel === 'email' ? 'fas fa-envelope' : 'fab fa-telegram'}"></i>
                        <strong>${m.channel === 'email' ? 'Email' : 'Telegram'}</strong> → ${esc(m.to)}
                        <span class="settings-sub">${esc(m.sent_at.replace('T', ' '))}</span></div>
                    ${m.subject ? `<div><strong>${esc(m.subject)}</strong></div>` : ''}
                    <pre style="white-space:pre-wrap;margin:4px 0 0;font:inherit">${esc(m.body.replace(/<\/?b>/g, ''))}</pre>
                </div>`).join('') : '<p class="settings-hint">No simulated messages yet. Click “Send test alert”.</p>';
        } catch (e) {
            console.warn('Settings.loadOutbox failed', e);
        }
    },

    /** Populate the form from the current user object (called when view opens). */
    async load() {
        this._setMsg();
        this.loadOutbox();
        try {
            const data = await API.getMe();
            const user = (data && data.user) || {};
            const setText = (id, val) => {
                const el = document.getElementById(id);
                if (el) el.textContent = val || '—';
            };
            setText('settings-email', user.email);
            setText('settings-name', user.display_name);

            const emailToggle = document.getElementById('settings-notify-email');
            if (emailToggle) emailToggle.checked = !!user.notify_email;

            // We don't echo the stored chat id back (server returns only has_telegram),
            // but reflect whether one is set via the placeholder.
            const tgField = document.getElementById('settings-telegram');
            if (tgField && user.has_telegram) {
                tgField.placeholder = '✓ A chat ID is saved (enter a new one to change it)';
            }
        } catch (e) {
            console.warn('Settings.load failed', e);
        }
    },

    async save() {
        this._setMsg();
        const btn = document.getElementById('btn-save-settings');
        const emailToggle = document.getElementById('settings-notify-email');
        const tgField = document.getElementById('settings-telegram');

        const payload = {};
        if (emailToggle) payload.notify_email = emailToggle.checked;
        if (tgField && !tgField.disabled) {
            const v = tgField.value.trim();
            // Only send when the user typed something, to avoid wiping an existing id by accident.
            if (v !== '') payload.telegram_chat_id = v;
        }

        if (btn) btn.disabled = true;
        try {
            const data = await API.updateSettings(payload);
            if (data && data.error) {
                this._setMsg('error', data.error);
                return;
            }
            this._setMsg('success', 'Notification settings saved.');
            if (tgField) tgField.value = '';
            await this.load();
        } catch (e) {
            console.error('Settings.save failed', e);
            this._setMsg('error', 'Connection error while saving settings.');
        } finally {
            if (btn) btn.disabled = false;
        }
    },
};

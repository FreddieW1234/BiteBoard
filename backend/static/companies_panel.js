/**
 * Companies tab on the staff Customers page.
 * Expects window.CU_DATA.customers for the add-member picker.
 */
(function (global) {
    'use strict';

    let companies = [];
    let expandedCompanyId = null;
    let companyDetailsCache = Object.create(null);
    let searchTerm = '';

    function escapeHtml(text) {
        const d = document.createElement('div');
        d.textContent = text == null ? '' : String(text);
        return d.innerHTML;
    }

    function todayIso() {
        const d = new Date();
        const m = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        return `${d.getFullYear()}-${m}-${day}`;
    }

    function formatDate(value) {
        if (!value) return '—';
        const d = new Date(value);
        if (Number.isNaN(d.getTime())) return String(value);
        return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
    }

    function formatGBP(amount) {
        const n = typeof amount === 'number' ? amount : parseFloat(amount) || 0;
        return n.toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function companyMemberIds(company) {
        if (Array.isArray(company.member_ids) && company.member_ids.length) {
            return company.member_ids.map(String);
        }
        return (company.members || []).map(m => String(m.customer_id)).filter(Boolean);
    }

    function companyTotalSpent(company) {
        const ids = new Set(companyMemberIds(company));
        if (!ids.size) return 0;
        const all = (global.CU_DATA && global.CU_DATA.customers) || [];
        let sum = 0;
        for (const c of all) {
            if (ids.has(String(c.id))) {
                sum += parseFloat(c.total_spent || 0) || 0;
            }
        }
        return sum;
    }

    function patchLinkedCustomersCompanyName(company) {
        if (!company || !global.CU_DATA || !Array.isArray(global.CU_DATA.customers)) return;
        const memberIds = new Set(companyMemberIds(company));
        const companyName = (company.name || '').trim();
        global.CU_DATA.customers.forEach(function (c) {
            if (memberIds.has(String(c.id))) {
                c.company_name = companyName;
                c.company_locked = true;
            }
        });
    }

    function filteredCompanies() {
        const term = (searchTerm || '').trim().toLowerCase();
        if (!term) return companies;
        return companies.filter(c => (c.name || '').toLowerCase().includes(term));
    }

    function availableCustomers(company) {
        const assigned = new Set((company.members || []).map(m => String(m.customer_id)));
        const all = (global.CU_DATA && global.CU_DATA.customers) || [];
        return all.filter(c => !assigned.has(String(c.id)));
    }

    function renderNoteRow(note) {
        return `<div class="co-note-item">
            <div class="co-note-meta">
                <strong>${escapeHtml(note.author || '')}</strong>
                <span>${escapeHtml(formatDate(note.note_date))}</span>
            </div>
            <div class="co-note-body">${escapeHtml(note.body || '')}</div>
        </div>`;
    }

    function renderMemberRow(companyId, member) {
        return `<div class="co-member-row">
            <div class="co-member-info">
                <strong>${escapeHtml(member.name || 'Unknown')}</strong>
                <span class="co-member-email">${escapeHtml(member.email || '')}</span>
            </div>
            <button type="button" class="btn-ghost co-remove-member" data-company-id="${escapeHtml(companyId)}" data-customer-id="${escapeHtml(member.customer_id)}">
                <i class="fas fa-user-minus"></i> Remove
            </button>
        </div>`;
    }

    function renderCompanyDetail(company) {
        const customers = availableCustomers(company);
        const options = customers.map(c =>
            `<option value="${escapeHtml(c.id)}">${escapeHtml(c.name || c.email)} (${escapeHtml(c.email || '')})</option>`
        ).join('');

        const notesHtml = (company.notes || []).length
            ? company.notes.map(renderNoteRow).join('')
            : '<p class="co-empty-hint">No notes yet.</p>';

        const membersHtml = (company.members || []).length
            ? company.members.map(m => renderMemberRow(company.id, m)).join('')
            : '<p class="co-empty-hint">No individuals linked yet.</p>';

        return `<div class="co-company-detail">
            <div class="co-company-detail-grid">
                <section class="co-company-section">
                    <h4>Company name</h4>
                    <form class="co-rename-form" data-company-id="${escapeHtml(company.id)}">
                        <div class="co-inline-field">
                            <input type="text" name="name" value="${escapeHtml(company.name || '')}" required>
                            <button type="submit" class="btn-ghost"><i class="fas fa-check"></i> Save name</button>
                        </div>
                    </form>
                </section>
                <section class="co-company-section">
                    <h4>Individuals</h4>
                    ${membersHtml}
                    <form class="co-add-member-form" data-company-id="${escapeHtml(company.id)}">
                        <div class="co-inline-field">
                            <select name="customer_id" required ${customers.length ? '' : 'disabled'}>
                                <option value="">Add individual…</option>
                                ${options}
                            </select>
                            <button type="submit" class="btn-primary" ${customers.length ? '' : 'disabled'}><i class="fas fa-user-plus"></i> Add</button>
                        </div>
                    </form>
                </section>
                <section class="co-company-section co-notes-section">
                    <h4>Notes</h4>
                    ${notesHtml}
                    <form class="co-add-note-form" data-company-id="${escapeHtml(company.id)}">
                        <div class="co-note-form-grid">
                            <label>
                                <span>Date</span>
                                <input type="date" name="note_date" value="${todayIso()}" required>
                            </label>
                            <label>
                                <span>Author</span>
                                <input type="text" name="author" placeholder="Your name" required>
                            </label>
                            <label class="co-note-body-field">
                                <span>Note</span>
                                <textarea name="body" rows="3" placeholder="Interaction notes…" required></textarea>
                            </label>
                        </div>
                        <button type="submit" class="btn-primary"><i class="fas fa-plus"></i> Add note</button>
                    </form>
                </section>
            </div>
        </div>`;
    }

    function renderCompaniesTable() {
        const root = document.getElementById('co-companies-content');
        const countEl = document.getElementById('co-companies-count');
        if (!root) return;

        const visible = filteredCompanies();
        if (countEl) {
            countEl.textContent = searchTerm
                ? `${visible.length} of ${companies.length}`
                : `${companies.length} total`;
        }

        if (!visible.length) {
            root.innerHTML = '<div class="list-card"><div class="state-msg">No companies found.</div></div>';
            return;
        }

        let rows = '';
        visible.forEach(company => {
            const expanded = String(expandedCompanyId) === String(company.id);
            const detail = expanded ? (companyDetailsCache[company.id] || company) : null;
            rows += `<tr class="co-company-row${expanded ? ' expanded' : ''}" data-company-id="${escapeHtml(company.id)}">
                <td><strong>${escapeHtml(company.name)}</strong><i class="fas fa-chevron-down co-company-chevron"></i></td>
                <td>${escapeHtml(String(company.member_count || 0))}</td>
                <td class="co-col-total">£${escapeHtml(formatGBP(companyTotalSpent(company)))}</td>
            </tr>`;
            if (expanded) {
                rows += `<tr class="co-company-details-row open"><td colspan="3">${detail ? renderCompanyDetail(detail) : '<div class="state-msg"><div class="spinner"></div>Loading…</div>'}</td></tr>`;
            }
        });

        root.innerHTML = `<div class="list-card"><div class="list-card-scroll">
            <table class="cust-table co-companies-table">
                <thead>
                    <tr>
                        <th>Company</th>
                        <th>Individuals</th>
                        <th class="co-col-total">Total</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        </div></div>`;
    }

    async function loadCompanies() {
        const root = document.getElementById('co-companies-content');
        if (root) {
            root.innerHTML = '<div class="list-card"><div class="state-msg"><div class="spinner"></div>Loading companies…</div></div>';
        }
        const resp = await fetch('/api/companies', { credentials: 'same-origin' });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.success) {
            throw new Error((data && data.error) || 'Failed to load companies');
        }
        companies = data.companies || [];
        companies.forEach(function (company) {
            const cached = companyDetailsCache[company.id];
            if (cached && Array.isArray(cached.members)) {
                company.members = cached.members;
            }
        });
        renderCompaniesTable();
    }

    async function loadCompanyDetail(companyId) {
        const resp = await fetch(`/api/companies/${encodeURIComponent(companyId)}`, { credentials: 'same-origin' });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.success) {
            throw new Error((data && data.error) || 'Failed to load company');
        }
        companyDetailsCache[companyId] = data.company;
        renderCompaniesTable();
    }

    async function createCompany(name) {
        const resp = await fetch('/api/companies', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ name }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.success) {
            throw new Error((data && data.error) || 'Could not create company');
        }
        await loadCompanies();
        expandedCompanyId = data.company && data.company.id;
        if (expandedCompanyId) await loadCompanyDetail(expandedCompanyId);
    }

    async function renameCompany(companyId, name) {
        const resp = await fetch(`/api/companies/${encodeURIComponent(companyId)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ name }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.success) throw new Error((data && data.error) || 'Save failed');
        companyDetailsCache[companyId] = data.company;
        patchLinkedCustomersCompanyName(data.company);
        const idx = companies.findIndex(c => String(c.id) === String(companyId));
        if (idx >= 0 && data.company) {
            companies[idx] = { ...companies[idx], name: data.company.name };
        }
        await loadCompanies();
        if (expandedCompanyId === companyId) {
            await loadCompanyDetail(companyId);
        }
        if (global.loadCustomers) await global.loadCustomers(true);
        if (typeof global.renderCustomers === 'function') global.renderCustomers();
    }

    async function addMember(companyId, customerId) {
        const resp = await fetch(`/api/companies/${encodeURIComponent(companyId)}/members`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ customer_id: customerId }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.success) throw new Error((data && data.error) || 'Could not add member');
        companyDetailsCache[companyId] = data.company;
        patchLinkedCustomersCompanyName(data.company);
        await loadCompanies();
        if (global.loadCustomers) await global.loadCustomers(true);
        if (typeof global.renderCustomers === 'function') global.renderCustomers();
    }

    async function removeMember(companyId, customerId) {
        const resp = await fetch(`/api/companies/${encodeURIComponent(companyId)}/members/${encodeURIComponent(customerId)}`, {
            method: 'DELETE',
            credentials: 'same-origin',
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.success) throw new Error((data && data.error) || 'Could not remove member');
        companyDetailsCache[companyId] = data.company;
        await loadCompanies();
        if (global.loadCustomers) await global.loadCustomers(true);
    }

    async function addNote(companyId, payload) {
        const resp = await fetch(`/api/companies/${encodeURIComponent(companyId)}/notes`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify(payload),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.success) throw new Error((data && data.error) || 'Could not save note');
        await loadCompanyDetail(companyId);
    }

    function bindEvents() {
        const root = document.getElementById('customers-view-companies');
        if (!root || root.dataset.bound === '1') return;
        root.dataset.bound = '1';

        root.addEventListener('click', function (e) {
            const row = e.target.closest('.co-company-row');
            if (row && !e.target.closest('button, input, select, textarea, form, a')) {
                const id = row.dataset.companyId;
                expandedCompanyId = expandedCompanyId === id ? null : id;
                renderCompaniesTable();
                if (expandedCompanyId && !companyDetailsCache[expandedCompanyId]) {
                    loadCompanyDetail(expandedCompanyId).catch(err => alert(err.message));
                }
                return;
            }
            const removeBtn = e.target.closest('.co-remove-member');
            if (removeBtn) {
                e.preventDefault();
                const companyId = removeBtn.dataset.companyId;
                const customerId = removeBtn.dataset.customerId;
                if (!confirm('Remove this individual from the company?')) return;
                removeMember(companyId, customerId).catch(err => alert(err.message));
            }
        });

        root.addEventListener('submit', function (e) {
            const createForm = e.target.closest('#co-create-company-form');
            if (createForm) {
                e.preventDefault();
                const name = (new FormData(createForm).get('name') || '').trim();
                if (!name) return;
                createCompany(name).catch(err => alert(err.message));
                createForm.reset();
                return;
            }
            const renameForm = e.target.closest('.co-rename-form');
            if (renameForm) {
                e.preventDefault();
                const companyId = renameForm.dataset.companyId;
                const name = (new FormData(renameForm).get('name') || '').trim();
                renameCompany(companyId, name).catch(err => alert(err.message));
                return;
            }
            const memberForm = e.target.closest('.co-add-member-form');
            if (memberForm) {
                e.preventDefault();
                const companyId = memberForm.dataset.companyId;
                const customerId = (new FormData(memberForm).get('customer_id') || '').trim();
                if (!customerId) return;
                addMember(companyId, customerId).catch(err => alert(err.message));
                return;
            }
            const noteForm = e.target.closest('.co-add-note-form');
            if (noteForm) {
                e.preventDefault();
                const companyId = noteForm.dataset.companyId;
                const fd = new FormData(noteForm);
                addNote(companyId, {
                    note_date: fd.get('note_date'),
                    author: fd.get('author'),
                    body: fd.get('body'),
                }).then(() => noteForm.querySelector('[name="body"]').value = '').catch(err => alert(err.message));
            }
        });

        const search = document.getElementById('co-companies-search');
        if (search) {
            search.addEventListener('input', function () {
                searchTerm = search.value || '';
                renderCompaniesTable();
            });
        }

        const refreshBtn = document.getElementById('co-companies-refresh');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', function () {
                companyDetailsCache = Object.create(null);
                loadCompanies().catch(err => alert(err.message));
            });
        }
    }

    function showCompaniesView() {
        bindEvents();
        loadCompanies().catch(err => {
            const root = document.getElementById('co-companies-content');
            if (root) root.innerHTML = `<div class="list-card"><div class="state-msg error">${escapeHtml(err.message)}</div></div>`;
        });
    }

    global.CompaniesPanel = {
        show: showCompaniesView,
        refreshList: loadCompanies,
    };
})(window);

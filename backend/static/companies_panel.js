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
    let noteModalCompanyId = null;
    let addMemberModalCompanyId = null;
    let addMemberPickerSearch = '';
    let companiesListLoaded = false;
    let companiesLoadPromise = null;
    let customerLookup = null;

    function ensureNoteModal() {
        let modal = document.getElementById('co-note-modal');
        if (modal) return modal;
        modal = document.createElement('div');
        modal.id = 'co-note-modal';
        modal.className = 'co-note-modal';
        modal.hidden = true;
        modal.innerHTML = `
            <div class="co-note-modal-backdrop" data-close-co-note-modal></div>
            <div class="co-note-modal-panel" role="dialog" aria-modal="true" aria-labelledby="co-note-modal-title">
                <div class="co-note-modal-header">
                    <h2 id="co-note-modal-title">Add note</h2>
                    <button type="button" class="co-note-modal-close" data-close-co-note-modal aria-label="Close">&times;</button>
                </div>
                <form id="co-note-modal-form" class="co-note-modal-body">
                    <div class="co-note-form-grid">
                        <label>
                            <span>Date</span>
                            <input type="date" name="note_date" required>
                        </label>
                        <label>
                            <span>Author</span>
                            <input type="text" name="author" placeholder="Your name" required autocomplete="name">
                        </label>
                        <label class="co-note-body-field">
                            <span>Note</span>
                            <textarea name="body" rows="8" placeholder="Interaction notes…" required></textarea>
                        </label>
                    </div>
                </form>
                <div class="co-note-modal-footer">
                    <button type="button" class="btn-ghost" data-close-co-note-modal>Cancel</button>
                    <button type="submit" form="co-note-modal-form" class="btn-primary" id="co-note-modal-save">
                        <i class="fas fa-check"></i> Save note
                    </button>
                </div>
            </div>`;
        document.body.appendChild(modal);

        modal.addEventListener('click', function (e) {
            if (e.target.closest('[data-close-co-note-modal]')) closeNoteModal();
        });

        document.getElementById('co-note-modal-form').addEventListener('submit', function (e) {
            e.preventDefault();
            if (!noteModalCompanyId) return;
            const form = e.target;
            const saveBtn = document.getElementById('co-note-modal-save');
            const fd = new FormData(form);
            if (saveBtn) {
                saveBtn.disabled = true;
                saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving…';
            }
            addNote(noteModalCompanyId, {
                note_date: fd.get('note_date'),
                author: fd.get('author'),
                body: fd.get('body'),
            }).then(function () {
                closeNoteModal();
            }).catch(function (err) {
                alert(err.message);
            }).finally(function () {
                if (saveBtn) {
                    saveBtn.disabled = false;
                    saveBtn.innerHTML = '<i class="fas fa-check"></i> Save note';
                }
            });
        });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && modal.classList.contains('open')) closeNoteModal();
        });

        return modal;
    }

    function openNoteModal(companyId, companyName) {
        const modal = ensureNoteModal();
        noteModalCompanyId = companyId;
        const form = document.getElementById('co-note-modal-form');
        const title = document.getElementById('co-note-modal-title');
        if (title) {
            title.textContent = companyName
                ? `Add note — ${companyName}`
                : 'Add note';
        }
        if (form) {
            form.reset();
            const dateInput = form.querySelector('[name="note_date"]');
            if (dateInput) dateInput.value = todayIso();
        }
        modal.hidden = false;
        modal.classList.add('open');
        const authorInput = form && form.querySelector('[name="author"]');
        if (authorInput) authorInput.focus();
    }

    function closeNoteModal() {
        const modal = document.getElementById('co-note-modal');
        if (!modal) return;
        modal.classList.remove('open');
        modal.hidden = true;
        noteModalCompanyId = null;
    }

    function ensureCreateCompanyModal() {
        let modal = document.getElementById('co-create-company-modal');
        if (modal) return modal;
        modal = document.createElement('div');
        modal.id = 'co-create-company-modal';
        modal.className = 'co-note-modal';
        modal.hidden = true;
        modal.innerHTML = `
            <div class="co-note-modal-backdrop" data-close-co-create-company></div>
            <div class="co-note-modal-panel" role="dialog" aria-modal="true" aria-labelledby="co-create-company-modal-title">
                <div class="co-note-modal-header">
                    <h2 id="co-create-company-modal-title">Create company</h2>
                    <button type="button" class="co-note-modal-close" data-close-co-create-company aria-label="Close">&times;</button>
                </div>
                <form id="co-create-company-modal-form" class="co-note-modal-body">
                    <label class="co-create-company-field">
                        <span>Company name</span>
                        <input type="text" name="name" placeholder="Company name" required autocomplete="organization">
                    </label>
                </form>
                <div class="co-note-modal-footer">
                    <button type="button" class="btn-ghost" data-close-co-create-company>Cancel</button>
                    <button type="submit" form="co-create-company-modal-form" class="btn-primary" id="co-create-company-modal-save">
                        <i class="fas fa-plus"></i> Create
                    </button>
                </div>
            </div>`;
        document.body.appendChild(modal);

        modal.addEventListener('click', function (e) {
            if (e.target.closest('[data-close-co-create-company]')) closeCreateCompanyModal();
        });

        document.getElementById('co-create-company-modal-form').addEventListener('submit', function (e) {
            e.preventDefault();
            const form = e.target;
            const saveBtn = document.getElementById('co-create-company-modal-save');
            const name = (new FormData(form).get('name') || '').trim();
            if (!name) return;
            if (saveBtn) {
                saveBtn.disabled = true;
                saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creating…';
            }
            createCompany(name).then(function () {
                closeCreateCompanyModal();
            }).catch(function (err) {
                alert(err.message);
            }).finally(function () {
                if (saveBtn) {
                    saveBtn.disabled = false;
                    saveBtn.innerHTML = '<i class="fas fa-plus"></i> Create';
                }
            });
        });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && modal.classList.contains('open')) closeCreateCompanyModal();
        });

        return modal;
    }

    function openCreateCompanyModal() {
        const modal = ensureCreateCompanyModal();
        const form = document.getElementById('co-create-company-modal-form');
        if (form) form.reset();
        modal.hidden = false;
        modal.classList.add('open');
        const nameInput = form && form.querySelector('[name="name"]');
        if (nameInput) nameInput.focus();
    }

    function closeCreateCompanyModal() {
        const modal = document.getElementById('co-create-company-modal');
        if (!modal) return;
        modal.classList.remove('open');
        modal.hidden = true;
    }

    function customerPickerHaystack(c) {
        return [
            c.name, c.first_name, c.last_name, c.email, c.company_name,
            c.phone, c.landline_phone, c.mobile_number,
        ].join(' ').toLowerCase();
    }

    function filteredPickerCustomers(company) {
        const term = (addMemberPickerSearch || '').trim().toLowerCase();
        let list = availableCustomers(company);
        if (term) {
            list = list.filter(c => customerPickerHaystack(c).includes(term));
        }
        return list.slice(0, 50);
    }

    function renderCustomerPickerResults() {
        const resultsEl = document.getElementById('co-add-member-results');
        if (!resultsEl || !addMemberModalCompanyId) return;

        const company = companyDetailsCache[addMemberModalCompanyId]
            || companies.find(c => String(c.id) === String(addMemberModalCompanyId));
        if (!company) {
            resultsEl.innerHTML = '<div class="co-customer-picker-empty">Company not found.</div>';
            return;
        }

        const matches = filteredPickerCustomers(company);
        if (!availableCustomers(company).length) {
            resultsEl.innerHTML = '<div class="co-customer-picker-empty">All customers are already linked to a company.</div>';
            return;
        }
        if (!matches.length) {
            resultsEl.innerHTML = '<div class="co-customer-picker-empty">No customers match your search.</div>';
            return;
        }

        resultsEl.innerHTML = matches.map(c => {
            const companyLine = (c.company_name || '').trim();
            const meta = [c.email || '', companyLine ? `Company: ${companyLine}` : ''].filter(Boolean).join(' · ');
            return `<button type="button" class="co-customer-picker-item" data-customer-id="${escapeHtml(c.id)}">
                <strong>${escapeHtml(c.name || c.email || 'Unknown')}</strong>
                <span>${escapeHtml(meta)}</span>
            </button>`;
        }).join('');
    }

    function ensureAddMemberModal() {
        let modal = document.getElementById('co-add-member-modal');
        if (modal) return modal;
        modal = document.createElement('div');
        modal.id = 'co-add-member-modal';
        modal.className = 'co-note-modal';
        modal.hidden = true;
        modal.innerHTML = `
            <div class="co-note-modal-backdrop" data-close-co-add-member></div>
            <div class="co-note-modal-panel" role="dialog" aria-modal="true" aria-labelledby="co-add-member-modal-title">
                <div class="co-note-modal-header">
                    <h2 id="co-add-member-modal-title">Add individual</h2>
                    <button type="button" class="co-note-modal-close" data-close-co-add-member aria-label="Close">&times;</button>
                </div>
                <div class="co-note-modal-body">
                    <div class="co-customer-picker-search-wrap">
                        <i class="fas fa-search"></i>
                        <input type="search" id="co-add-member-search" placeholder="Search by name, email, or company…" autocomplete="off">
                    </div>
                    <div id="co-add-member-results" class="co-customer-picker-results"></div>
                </div>
                <div class="co-note-modal-footer">
                    <button type="button" class="btn-ghost" data-close-co-add-member>Cancel</button>
                </div>
            </div>`;
        document.body.appendChild(modal);

        modal.addEventListener('click', function (e) {
            if (e.target.closest('[data-close-co-add-member]')) closeAddMemberModal();
            const pick = e.target.closest('.co-customer-picker-item');
            if (pick && addMemberModalCompanyId) {
                const customerId = pick.dataset.customerId;
                if (!customerId) return;
                pick.disabled = true;
                addMember(addMemberModalCompanyId, customerId)
                    .then(function () { closeAddMemberModal(); })
                    .catch(function (err) {
                        alert(err.message);
                        pick.disabled = false;
                    });
            }
        });

        const searchInput = document.getElementById('co-add-member-search');
        if (searchInput) {
            searchInput.addEventListener('input', function () {
                addMemberPickerSearch = searchInput.value || '';
                renderCustomerPickerResults();
            });
        }

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && modal.classList.contains('open')) closeAddMemberModal();
        });

        return modal;
    }

    function openAddMemberModal(companyId, companyName) {
        const modal = ensureAddMemberModal();
        addMemberModalCompanyId = companyId;
        addMemberPickerSearch = '';
        const title = document.getElementById('co-add-member-modal-title');
        if (title) {
            title.textContent = companyName
                ? `Add individual — ${companyName}`
                : 'Add individual';
        }
        const searchInput = document.getElementById('co-add-member-search');
        if (searchInput) searchInput.value = '';
        renderCustomerPickerResults();
        modal.hidden = false;
        modal.classList.add('open');
        if (searchInput) searchInput.focus();
    }

    function closeAddMemberModal() {
        const modal = document.getElementById('co-add-member-modal');
        if (!modal) return;
        modal.classList.remove('open');
        modal.hidden = true;
        addMemberModalCompanyId = null;
        addMemberPickerSearch = '';
    }

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

    function rebuildCustomerLookup() {
        customerLookup = Object.create(null);
        const all = (global.CU_DATA && global.CU_DATA.customers) || [];
        for (const c of all) {
            customerLookup[String(c.id)] = c;
        }
    }

    function customerLookupById() {
        if (!customerLookup) rebuildCustomerLookup();
        return customerLookup;
    }

    function enrichCompanyFromCuData(company) {
        if (!company) return company;
        const lookup = customerLookupById();
        let members = company.members;
        if (!members || !members.length) {
            members = companyMemberIds(company).map(function (id) {
                const c = lookup[id];
                return {
                    customer_id: id,
                    name: c ? (c.name || '') : '',
                    email: c ? (c.email || '') : '',
                };
            });
        } else {
            members = members.map(function (m) {
                const id = String(m.customer_id || '');
                const c = lookup[id];
                if (!c) return m;
                return {
                    customer_id: id,
                    added_at: m.added_at || '',
                    name: m.name || c.name || '',
                    email: m.email || c.email || '',
                };
            });
        }
        return Object.assign({}, company, { members: members });
    }

    function companyTotalSpent(company) {
        const lookup = customerLookupById();
        const ids = companyMemberIds(company);
        if (!ids.length) return 0;
        let sum = 0;
        for (let i = 0; i < ids.length; i++) {
            const c = lookup[ids[i]];
            if (c) sum += parseFloat(c.total_spent || 0) || 0;
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

    function renderNoteRow(companyId, note) {
        return `<div class="co-note-item">
            <div class="co-note-meta">
                <strong>${escapeHtml(note.author || '')}</strong>
                <span>${escapeHtml(formatDate(note.note_date))}</span>
                <button type="button" class="btn-ghost co-delete-note" data-company-id="${escapeHtml(companyId)}" data-note-id="${escapeHtml(note.id)}" title="Delete note">
                    <i class="fas fa-trash"></i> Delete
                </button>
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
        company = enrichCompanyFromCuData(company);
        const availableCount = availableCustomers(company).length;

        const notesHtml = (company.notes || []).length
            ? company.notes.map(function (n) { return renderNoteRow(company.id, n); }).join('')
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
                    <div class="co-individuals-header">
                        <h4>Individuals</h4>
                        <button type="button" class="btn-primary co-add-member-btn" data-company-id="${escapeHtml(company.id)}"${availableCount ? '' : ' disabled title="No unlinked customers"'}>
                            <i class="fas fa-user-plus"></i> Add individual
                        </button>
                    </div>
                    ${membersHtml}
                </section>
                <section class="co-company-section co-notes-section">
                    <div class="co-notes-header">
                        <h4>Notes</h4>
                        <button type="button" class="btn-primary co-add-note-btn" data-company-id="${escapeHtml(company.id)}">
                            <i class="fas fa-plus"></i> Add note
                        </button>
                    </div>
                    ${notesHtml}
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

    async function loadCompanies(options) {
        options = options || {};
        const force = !!options.force;
        const silent = !!options.silent;

        if (!force && companiesListLoaded) {
            renderCompaniesTable();
            return;
        }
        if (companiesLoadPromise && !force) {
            return companiesLoadPromise;
        }

        const root = document.getElementById('co-companies-content');
        const view = document.getElementById('customers-view-companies');
        if (root && !silent && view && !view.hidden) {
            root.innerHTML = '<div class="list-card"><div class="state-msg"><div class="spinner"></div>Loading companies…</div></div>';
        }

        companiesLoadPromise = (async function () {
            const url = force ? '/api/companies?refresh=1' : '/api/companies';
            const resp = await fetch(url, { credentials: 'same-origin' });
            const data = await resp.json().catch(function () { return {}; });
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
            companiesListLoaded = true;
            renderCompaniesTable();
        })();

        try {
            await companiesLoadPromise;
        } catch (err) {
            if (!silent) throw err;
            companiesListLoaded = false;
        } finally {
            if (force) companiesLoadPromise = null;
        }
    }

    async function loadCompanyDetail(companyId) {
        const resp = await fetch(`/api/companies/${encodeURIComponent(companyId)}`, { credentials: 'same-origin' });
        const data = await resp.json().catch(function () { return {}; });
        if (!resp.ok || !data.success) {
            throw new Error((data && data.error) || 'Failed to load company');
        }
        companyDetailsCache[companyId] = enrichCompanyFromCuData(data.company);
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
        await loadCompanies({ force: true });
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
        await loadCompanies({ force: true });
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
        await loadCompanies({ force: true });
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
        await loadCompanies({ force: true });
        if (global.loadCustomers) await global.loadCustomers(true);
    }

    async function addNote(companyId, payload) {
        const resp = await fetch(`/api/companies/${encodeURIComponent(companyId)}/notes`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify(payload),
        });
        const data = await resp.json().catch(function () { return {}; });
        if (!resp.ok || !data.success) throw new Error((data && data.error) || 'Could not save note');
        await loadCompanyDetail(companyId);
    }

    async function deleteNote(companyId, noteId) {
        const resp = await fetch(
            `/api/companies/${encodeURIComponent(companyId)}/notes/${encodeURIComponent(noteId)}`,
            { method: 'DELETE', credentials: 'same-origin' }
        );
        const data = await resp.json().catch(function () { return {}; });
        if (!resp.ok || !data.success) {
            throw new Error((data && data.error) || 'Could not delete note');
        }
        if (data.company) {
            companyDetailsCache[companyId] = enrichCompanyFromCuData(data.company);
        } else {
            await loadCompanyDetail(companyId);
        }
        renderCompaniesTable();
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
                if (expandedCompanyId) {
                    const summary = companies.find(function (c) {
                        return String(c.id) === String(expandedCompanyId);
                    });
                    const cached = companyDetailsCache[expandedCompanyId];
                    if (!cached && summary) {
                        companyDetailsCache[expandedCompanyId] = enrichCompanyFromCuData(summary);
                    }
                }
                renderCompaniesTable();
                if (expandedCompanyId) {
                    const cached = companyDetailsCache[expandedCompanyId];
                    if (!cached || !Array.isArray(cached.notes)) {
                        loadCompanyDetail(expandedCompanyId).catch(function (err) { alert(err.message); });
                    }
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
                return;
            }
            const addNoteBtn = e.target.closest('.co-add-note-btn');
            if (addNoteBtn) {
                e.preventDefault();
                e.stopPropagation();
                const companyId = addNoteBtn.dataset.companyId;
                const company = companyDetailsCache[companyId] || companies.find(c => String(c.id) === String(companyId));
                openNoteModal(companyId, company && company.name);
                return;
            }
            const deleteNoteBtn = e.target.closest('.co-delete-note');
            if (deleteNoteBtn) {
                e.preventDefault();
                e.stopPropagation();
                const companyId = deleteNoteBtn.dataset.companyId;
                const noteId = deleteNoteBtn.dataset.noteId;
                if (!confirm('Delete this note? This cannot be undone.')) return;
                deleteNote(companyId, noteId).catch(function (err) { alert(err.message); });
                return;
            }
            const addMemberBtn = e.target.closest('.co-add-member-btn');
            if (addMemberBtn) {
                e.preventDefault();
                e.stopPropagation();
                if (addMemberBtn.disabled) return;
                const companyId = addMemberBtn.dataset.companyId;
                const company = companyDetailsCache[companyId] || companies.find(c => String(c.id) === String(companyId));
                openAddMemberModal(companyId, company && company.name);
            }
        });

        root.addEventListener('submit', function (e) {
            const renameForm = e.target.closest('.co-rename-form');
            if (renameForm) {
                e.preventDefault();
                const companyId = renameForm.dataset.companyId;
                const name = (new FormData(renameForm).get('name') || '').trim();
                renameCompany(companyId, name).catch(err => alert(err.message));
                return;
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
                companiesListLoaded = false;
                loadCompanies({ force: true }).catch(function (err) { alert(err.message); });
            });
        }

        const createBtn = document.getElementById('co-companies-create');
        if (createBtn) {
            createBtn.addEventListener('click', function () {
                openCreateCompanyModal();
            });
        }
    }

    function onCustomersLoaded() {
        rebuildCustomerLookup();
        if (companiesListLoaded) {
            renderCompaniesTable();
        }
    }

    function preloadCompanies() {
        return loadCompanies({ silent: true });
    }

    function showCompaniesView() {
        bindEvents();
        rebuildCustomerLookup();
        if (companiesListLoaded) {
            renderCompaniesTable();
            return;
        }
        loadCompanies().catch(function (err) {
            const root = document.getElementById('co-companies-content');
            if (root) root.innerHTML = `<div class="list-card"><div class="state-msg error">${escapeHtml(err.message)}</div></div>`;
        });
    }

    global.CompaniesPanel = {
        show: showCompaniesView,
        preload: preloadCompanies,
        refreshList: function () { return loadCompanies({ force: true }); },
        onCustomersLoaded: onCustomersLoaded,
    };
})(window);

/**
 * Allergen / dietary mapping shared by Product Manager and Field Finder.
 */
(function (global) {
    'use strict';

    const SUITABLE_FOR_KEYS = ['vegan', 'vegetarian', 'halal', 'coeliac', 'kosher'];

    const ALLERGEN_KEYS = [
        'celery', 'cereals', 'crustaceans', 'egg', 'fish', 'lupin', 'milk', 'molluscs',
        'mustard', 'nuts', 'peanuts', 'sesame', 'soya', 'sulphurdioxide',
    ];

    const ALLERGEN_SENTENCES = {
        celery: {
            contains: 'Celery present as an ingredient.',
            may_contain: 'Possible cross-contact with celery.',
            free_from: 'No celery intentionally used and no credible cross-contact risk.',
        },
        cereals: {
            contains: 'Gluten-containing cereal present as an ingredient.',
            may_contain: 'Possible cross-contact with gluten-containing cereals.',
            free_from: 'No gluten-containing cereals intentionally used and controlled to avoid cross-contact.',
        },
        crustaceans: {
            contains: 'Crustaceans present as an ingredient.',
            may_contain: 'Possible cross-contact with crustaceans.',
            free_from: 'No crustaceans intentionally used and controlled to avoid cross-contact.',
        },
        egg: {
            contains: 'Eggs present as an ingredient.',
            may_contain: 'Possible cross-contact with eggs.',
            free_from: 'No eggs intentionally used and controlled to avoid cross-contact.',
        },
        fish: {
            contains: 'Fish present as an ingredient.',
            may_contain: 'Possible cross-contact with fish.',
            free_from: 'No fish intentionally used and controlled to avoid cross-contact.',
        },
        lupin: {
            contains: 'Lupin present as an ingredient.',
            may_contain: 'Possible cross-contact with lupin.',
            free_from: 'No lupin intentionally used and controlled to avoid cross-contact.',
        },
        milk: {
            contains: 'Milk present as an ingredient.',
            may_contain: 'Possible cross-contact with milk.',
            free_from: 'No milk intentionally used and controlled to avoid cross-contact.',
        },
        molluscs: {
            contains: 'Molluscs present as an ingredient.',
            may_contain: 'Possible cross-contact with molluscs.',
            free_from: 'No molluscs intentionally used and controlled to avoid cross-contact.',
        },
        mustard: {
            contains: 'Mustard present as an ingredient.',
            may_contain: 'Possible cross-contact with mustard.',
            free_from: 'No mustard intentionally used and controlled to avoid cross-contact.',
        },
        nuts: {
            contains: 'Nuts present as an ingredient.',
            may_contain: 'Possible cross-contact with nuts.',
            free_from: 'No nuts intentionally used and controlled to avoid cross-contact.',
        },
        peanuts: {
            contains: 'Peanuts present as an ingredient.',
            may_contain: 'Possible cross-contact with peanuts.',
            free_from: 'No peanuts intentionally used and controlled to avoid cross-contact.',
        },
        sesame: {
            contains: 'Sesame seeds present as an ingredient.',
            may_contain: 'Possible cross-contact with sesame.',
            free_from: 'No sesame intentionally used and controlled to avoid cross-contact.',
        },
        soya: {
            contains: 'Soya present as an ingredient.',
            may_contain: 'Possible cross-contact with soya.',
            free_from: 'No soya intentionally used and controlled to avoid cross-contact.',
        },
        sulphurdioxide: {
            contains: 'Sulphites present above the threshold.',
            may_contain: 'Possible cross-contact or trace presence.',
            free_from: 'No sulphites above the threshold and controlled to avoid contamination.',
        },
    };

    const BODY_SUITABLE_LABELS = {
        vegan: 'Suitable for Vegans',
        vegetarian: 'Suitable for Vegetarians',
        halal: 'Halal (Not certified)',
        coeliac: 'Suitable for Coeliac',
        kosher: 'Suitable for Kosher',
    };

    // Appended to the tick/cross when saving suitable-for metafields
    // (e.g. "✔️ Vegan", "❌ Vegetarian Veggie").
    const SUITABLE_SAVE_SUFFIX = {
        vegan: 'Vegan',
        vegetarian: 'Vegetarian Veggie',
        kosher: 'Kosher',
        halal: 'Halal',
        coeliac: 'Coeliac',
    };

    const BODY_ALLERGEN_LABELS = {
        celery: 'Celery',
        cereals: 'Cereals containing gluten',
        crustaceans: 'Crustaceans',
        egg: 'Egg',
        fish: 'Fish',
        lupin: 'Lupin',
        milk: 'Milk',
        molluscs: 'Molluscs',
        mustard: 'Mustard',
        nuts: 'Nuts',
        peanuts: 'Peanuts',
        sesame: 'Sesame Seeds',
        soya: 'Soya',
        sulphurdioxide: 'Sulphur Dioxide',
    };

    const DISPLAY_NAME_OVERRIDES = {
        description: 'Description',
        vegan: 'Suitable for: Vegans',
        vegetarian: 'Suitable for: Vegetarians',
        halal: 'Suitable for: Halal (Not certified)',
        coeliac: 'Suitable for: Coeliacs',
        kosher: 'Suitable for: Kosher',
        celery: 'Celery',
        cereals: 'Cereals containing gluten',
        crustaceans: 'Crustaceans',
        egg: 'Egg',
        fish: 'Fish',
        lupin: 'Lupin',
        milk: 'Milk',
        molluscs: 'Molluscs',
        mustard: 'Mustard',
        nuts: 'Nuts',
        peanuts: 'Peanuts',
        sesame: 'Sesame Seeds',
        soya: 'Soya',
        sulphurdioxide: 'Sulphur Dioxide',
    };

    const DIETARY_SECTION_HEADING = 'Dietary/Allergens';
    const PRODUCT_INFO_METAFIELD_KEY = 'productinfo';
    const SHOPIFY_NATIVE_DESCRIPTION_HTML =
        '<h3><span>Product Info</span><span></span></h3>\n' +
        '<h3><span>Ingredients</span><span></span></h3>\n' +
        '<h3><span>Dietary/Allergens</span><span></span><span></span></h3>';
    const DEFAULT_PRODUCT_DESCRIPTION = '';

    function shopifyNativeDescriptionHtml() {
        return '';
    }

    const ALLERGEN_LEVELS = [
        { value: 'contains', label: 'Contains' },
        { value: 'may_contain', label: 'May Contain' },
        { value: 'free_from', label: 'Free From' },
    ];

    function decodeHtmlEntities(text) {
        const el = document.createElement('textarea');
        el.innerHTML = text;
        return el.value;
    }

    function parseShopifyBodyHtmlSections(bodyHtml) {
        const result = { productinfo: '', ingredients: '', dietary_lines: [] };
        if (!bodyHtml || typeof bodyHtml !== 'string') return result;
        const lines = [];
        const re = /<h3><span>([\s\S]*?)<\/span>/gi;
        let match;
        while ((match = re.exec(bodyHtml)) !== null) {
            const raw = match[1].replace(/<[^>]+>/g, '');
            lines.push(decodeHtmlEntities(raw).trim());
        }
        let i = 0;
        while (i < lines.length) {
            const line = lines[i];
            if (line === 'Product Info') {
                i += 1;
                const parts = [];
                while (i < lines.length && lines[i] !== 'Ingredients' && lines[i] !== DIETARY_SECTION_HEADING && lines[i] !== 'Dietary') {
                    parts.push(lines[i]);
                    i += 1;
                }
                result.productinfo = parts.join('\n').trim();
                continue;
            }
            if (line === 'Ingredients') {
                i += 1;
                const parts = [];
                while (i < lines.length && lines[i] !== 'Product Info' && lines[i] !== DIETARY_SECTION_HEADING && lines[i] !== 'Dietary') {
                    parts.push(lines[i]);
                    i += 1;
                }
                result.ingredients = parts.join('\n').trim();
                continue;
            }
            if (line === DIETARY_SECTION_HEADING || line === 'Dietary') {
                i += 1;
                while (i < lines.length && lines[i] !== 'Product Info' && lines[i] !== 'Ingredients') {
                    result.dietary_lines.push(lines[i]);
                    i += 1;
                }
                continue;
            }
            i += 1;
        }
        return result;
    }

    function applyParsedBodySectionsToDom(sections) {
        if (!sections) return;
        const piEl = document.querySelector('textarea.metafield-value[data-key="productinfo"]');
        if (piEl && !(piEl.value || '').trim() && sections.productinfo) {
            piEl.value = sections.productinfo;
            piEl.dispatchEvent(new Event('input', { bubbles: true }));
        }
        const ingEl = document.querySelector('textarea.metafield-value[data-key="ingredients"]');
        if (ingEl && !(ingEl.value || '').trim() && sections.ingredients) {
            ingEl.value = sections.ingredients;
            ingEl.dispatchEvent(new Event('input', { bubbles: true }));
        }
    }

    function allergenSentence(key, level) {
        const mapping = ALLERGEN_SENTENCES[key] || {};
        return mapping[level] || '';
    }

    function inferAllergenLevel(key, storedValue) {
        const val = String(storedValue || '').trim();
        if (!val) return '';
        if (val === '✔️' || val === '✅') return 'contains';
        if (val === '❌') return 'free_from';
        const mapping = ALLERGEN_SENTENCES[key] || {};
        for (const level of Object.keys(mapping)) {
            if (val === mapping[level]) return level;
        }
        const lower = val.toLowerCase();
        for (const level of Object.keys(mapping)) {
            if (mapping[level].toLowerCase() === lower) return level;
        }
        return '';
    }

    function isSuitableForKey(key) {
        return SUITABLE_FOR_KEYS.includes(key);
    }

    function isAllergenKey(key) {
        return ALLERGEN_KEYS.includes(key);
    }

    function suitableEmojiFromStored(value) {
        const v = String(value || '').trim();
        if (!v) return '';
        if (v === '✔️' || v.startsWith('✔️') || v === '✅' || v.startsWith('✅')) return '✔️';
        if (v === '❌' || v.startsWith('❌')) return '❌';
        return '';
    }

    function formatSuitableForSave(key, emojiOrValue) {
        const emoji = suitableEmojiFromStored(emojiOrValue) || String(emojiOrValue || '').trim();
        if (emoji !== '✔️' && emoji !== '❌') return String(emojiOrValue || '').trim();
        const word = SUITABLE_SAVE_SUFFIX[key];
        if (!word) return emoji;
        return emoji + ' ' + word;
    }

    function ensureDietaryMetafields(metafields) {
        const list = (metafields || []).slice();
        const byKey = new Map();
        list.forEach(function (m) {
            if (m && m.key) byKey.set(m.key, m);
        });
        if (byKey.has('tree_nuts') && !byKey.has('nuts')) {
            const legacy = byKey.get('tree_nuts');
            list.push({
                namespace: 'custom',
                key: 'nuts',
                type: legacy.type || 'single_line_text_field',
                value: legacy.value || '',
                id: null,
            });
            byKey.set('nuts', list[list.length - 1]);
        } else if (byKey.has('tree_nuts') && byKey.has('nuts')) {
            const nuts = byKey.get('nuts');
            if (!(nuts.value || '').trim() && (byKey.get('tree_nuts').value || '').trim()) {
                nuts.value = byKey.get('tree_nuts').value;
            }
        }
        SUITABLE_FOR_KEYS.concat(ALLERGEN_KEYS).forEach(function (key) {
            if (!byKey.has(key)) {
                list.push({
                    namespace: 'custom',
                    key: key,
                    type: 'single_line_text_field',
                    value: '',
                    id: null,
                });
            }
        });
        return list;
    }

    function buildAllergenDropdownHtml(metafield) {
        const key = metafield.key || '';
        const level = inferAllergenLevel(key, metafield.value || '');
        const options = ALLERGEN_LEVELS.map(function (opt) {
            const sentence = allergenSentence(key, opt.value);
            const selected = level === opt.value ? ' selected' : '';
            return `<option value="${opt.value}" data-sentence="${escapeAttr(sentence)}"${selected}>${opt.label}</option>`;
        }).join('');
        return `<select class="metafield-value allergen-dropdown" data-id="${metafield.id || 'null'}" data-namespace="${metafield.namespace || 'custom'}" data-key="${escapeHtml(key)}" data-type="${metafield.type || 'single_line_text_field'}">
            <option value="">-- Select --</option>
            ${options}
        </select>`;
    }

    function buildSuitableEmojiFieldHtml(metafield) {
        const currentValue = metafield.value || '';
        const selectedEmoji = suitableEmojiFromStored(currentValue);
        return `<div class="emoji-field-container" data-id="${metafield.id || 'null'}" data-namespace="${metafield.namespace || 'custom'}" data-key="${metafield.key || ''}" data-type="${metafield.type || 'single_line_text_field'}" data-selected-value="${escapeAttr(selectedEmoji)}">
            <div class="emoji-buttons">
                <button type="button" class="emoji-btn tick ${selectedEmoji === '✔️' ? 'selected' : ''}" data-emoji="✔️"><span>✔️</span></button>
                <button type="button" class="emoji-btn cross ${selectedEmoji === '❌' ? 'selected' : ''}" data-emoji="❌"><span>❌</span></button>
            </div>
        </div>`;
    }

    function escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function escapeAttr(s) {
        return escapeHtml(s).replace(/'/g, '&#39;');
    }

    function getAllergenValueFromSelect(selectEl) {
        if (!selectEl || selectEl.tagName !== 'SELECT') return '';
        const level = (selectEl.value || '').trim();
        if (!level) return '';
        const opt = selectEl.options[selectEl.selectedIndex];
        if (opt && opt.dataset && opt.dataset.sentence) return opt.dataset.sentence;
        return allergenSentence(selectEl.dataset.key, level);
    }

    const ALLERGEN_LEVEL_CLASSNAMES = ['allergen-level-contains', 'allergen-level-may_contain', 'allergen-level-free_from'];

    function applyAllergenDropdownStyle(selectEl) {
        if (!selectEl || selectEl.tagName !== 'SELECT') return;
        selectEl.classList.remove.apply(selectEl.classList, ALLERGEN_LEVEL_CLASSNAMES);
        const level = (selectEl.value || '').trim();
        if (level === 'contains') selectEl.classList.add('allergen-level-contains');
        else if (level === 'may_contain') selectEl.classList.add('allergen-level-may_contain');
        else if (level === 'free_from') selectEl.classList.add('allergen-level-free_from');
    }

    function bindAllergenDropdownStyles(root) {
        const scope = root || document;
        scope.querySelectorAll('select.allergen-dropdown').forEach(function (el) {
            applyAllergenDropdownStyle(el);
            if (el.dataset.allergenColorBound === '1') return;
            el.dataset.allergenColorBound = '1';
            el.addEventListener('change', function () {
                applyAllergenDropdownStyle(el);
            });
        });
    }

    function buildDietaryAllergensSectionLines(mfMap) {
        const lines = [];
        SUITABLE_FOR_KEYS.forEach(function (key) {
            const val = String((mfMap && mfMap[key]) || '').trim();
            if (!val) return;
            // Metafield may be "✔️ Vegan"; description line already has the label.
            const emoji = suitableEmojiFromStored(val) || val;
            lines.push(BODY_SUITABLE_LABELS[key] + ' ' + emoji);
        });
        ALLERGEN_KEYS.forEach(function (key) {
            const val = String((mfMap && mfMap[key]) || '').trim();
            if (!val && mfMap && key === 'nuts' && mfMap.tree_nuts) {
                const legacy = String(mfMap.tree_nuts).trim();
                if (legacy) lines.push(BODY_ALLERGEN_LABELS.nuts + ' ' + legacy);
                return;
            }
            if (val) lines.push(BODY_ALLERGEN_LABELS[key] + ' ' + val);
        });
        return lines;
    }

    function buildShopifyBodyPlainText(mfMap) {
        const productInfo = String((mfMap && mfMap[PRODUCT_INFO_METAFIELD_KEY]) || '').trim();
        const ingredients = String((mfMap && mfMap.ingredients) || '').trim();
        const dietaryLines = buildDietaryAllergensSectionLines(mfMap || {});
        const chunks = ['Product Info', '', productInfo, '', 'Ingredients', '', ingredients, '', DIETARY_SECTION_HEADING, ''].concat(dietaryLines);
        while (chunks.length && chunks[chunks.length - 1] === '') chunks.pop();
        return chunks.join('\n');
    }

    function metafieldsArrayToMap(metafields) {
        const map = {};
        (metafields || []).forEach(function (mf) {
            if (!mf || (mf.namespace || 'custom') !== 'custom') return;
            if (mf.key) map[mf.key] = mf.value;
        });
        if (!String(map.nuts || '').trim() && String(map.tree_nuts || '').trim()) {
            map.nuts = map.tree_nuts;
        }
        return map;
    }

    function collectDietaryMapFromDom(root) {
        const scope = root || document;
        const map = {};
        scope.querySelectorAll('.emoji-field-container').forEach(function (el) {
            const key = el.dataset.key;
            if (!key || !isSuitableForKey(key)) return;
            const val = formatSuitableForSave(key, el.dataset.selectedValue || '');
            if (val) map[key] = val;
        });
        scope.querySelectorAll('select.allergen-dropdown').forEach(function (el) {
            const key = el.dataset.key;
            if (!key) return;
            const val = getAllergenValueFromSelect(el);
            if (val) map[key] = val;
        });
        const productInfoEl = scope.querySelector('textarea.metafield-value[data-key="productinfo"]');
        const ingEl = scope.querySelector('textarea.metafield-value[data-key="ingredients"]');
        if (productInfoEl) map[PRODUCT_INFO_METAFIELD_KEY] = productInfoEl.value || '';
        if (ingEl) map.ingredients = ingEl.value || '';
        return map;
    }

    function ensureEditorMetafields(metafields) {
        let list = ensureDietaryMetafields(metafields);
        if (!list.some(function (m) { return m && m.key === PRODUCT_INFO_METAFIELD_KEY; })) {
            list = list.concat([{
                namespace: 'custom',
                key: PRODUCT_INFO_METAFIELD_KEY,
                type: 'single_line_text_field',
                value: '',
                id: null,
            }]);
        }
        return list;
    }

    function defaultMetafieldOrderDietaryTail() {
        return SUITABLE_FOR_KEYS.concat(ALLERGEN_KEYS);
    }

    global.AllergenMapping = {
        SUITABLE_FOR_KEYS,
        ALLERGEN_KEYS,
        ALLERGEN_SENTENCES,
        DISPLAY_NAME_OVERRIDES,
        DIETARY_SECTION_HEADING,
        PRODUCT_INFO_METAFIELD_KEY,
        SHOPIFY_NATIVE_DESCRIPTION_HTML,
        shopifyNativeDescriptionHtml,
        DEFAULT_PRODUCT_DESCRIPTION,
        allergenSentence,
        inferAllergenLevel,
        isSuitableForKey,
        isAllergenKey,
        suitableEmojiFromStored,
        formatSuitableForSave,
        SUITABLE_SAVE_SUFFIX,
        ensureDietaryMetafields,
        buildAllergenDropdownHtml,
        buildSuitableEmojiFieldHtml,
        getAllergenValueFromSelect,
        applyAllergenDropdownStyle,
        bindAllergenDropdownStyles,
        buildShopifyBodyPlainText,
        metafieldsArrayToMap,
        ensureEditorMetafields,
        parseShopifyBodyHtmlSections,
        applyParsedBodySectionsToDom,
        collectDietaryMapFromDom,
        defaultMetafieldOrderDietaryTail,
    };
})(typeof window !== 'undefined' ? window : globalThis);

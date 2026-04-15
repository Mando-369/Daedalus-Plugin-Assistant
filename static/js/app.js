/**
 * Daedalus Plugin Assistant - Frontend Application
 * Handles tabs, chat (WebSocket), browse/filter, review, stats, and CRUD editing.
 */

const App = (() => {
    // ── State ────────────────────────────────────
    let ws = null;
    let chatHistory = [];
    let currentPage = 1;
    let reviewPage = 1;
    let debounceTimer = null;
    let currentConversationId = null;

    // ── Initialization ──────────────────────────
    function init() {
        connectWebSocket();
        loadFilters();
        loadStats();
        loadReviewBadge();
        loadConversations();
    }

    function connectWebSocket() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        ws = new WebSocket(`${proto}//${location.host}/ws/chat`);

        ws.onopen = () => console.log('WebSocket connected');
        ws.onclose = () => {
            console.log('WebSocket closed, reconnecting in 3s...');
            setTimeout(connectWebSocket, 3000);
        };
        ws.onerror = (e) => console.error('WebSocket error:', e);
        ws.onmessage = handleWSMessage;
    }

    // ── Tab Switching ───────────────────────────
    function switchTab(tab) {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        document.querySelector(`[data-tab="${tab}"]`).classList.add('active');
        document.getElementById(`tab-${tab}`).classList.add('active');

        if (tab === 'browse') loadPlugins();
        if (tab === 'review') loadReviewPlugins();
        if (tab === 'stats') loadStats();
        if (tab === 'settings') { loadSettings(); loadScanDirs(); }
    }

    // ── Chat ────────────────────────────────────
    async function sendMessage() {
        const input = document.getElementById('chat-input');
        const text = input.value.trim();
        if (!text) return;

        // Auto-create conversation if none active
        if (!currentConversationId) {
            await newConversation();
        }

        // Clear welcome message on first send
        const welcome = document.querySelector('.chat-welcome');
        if (welcome) welcome.remove();

        // Add user message
        appendChatMessage('user', text);
        chatHistory.push({ role: 'user', content: text });

        // Send via WebSocket
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                message: text,
                history: chatHistory.slice(-6),
                conversation_id: currentConversationId,
            }));
            // Create placeholder for assistant response
            appendChatMessage('assistant', '', true);
        } else {
            fetchChat(text);
        }

        input.value = '';
        input.style.height = 'auto';
        // Refresh sidebar to show updated title
        loadConversations();
    }

    function sendSuggestion(el) {
        document.getElementById('chat-input').value = el.textContent;
        sendMessage();
    }

    function handleChatKey(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
        // Auto-resize
        const el = e.target;
        el.style.height = 'auto';
        el.style.height = Math.min(el.scrollHeight, 120) + 'px';
    }

    let currentAssistantEl = null;
    let isInThinking = false;

    function handleWSMessage(event) {
        const data = JSON.parse(event.data);

        switch (data.type) {
            case 'status':
                updateStreamStatus(data.content);
                break;
            case 'sources':
                // Store sources to append after done
                if (currentAssistantEl) {
                    currentAssistantEl._sources = data.content;
                }
                break;
            case 'thinking':
                if (currentAssistantEl) {
                    // Create thinking block on first thinking token
                    if (!isInThinking) {
                        isInThinking = true;
                        const body = currentAssistantEl.querySelector('.msg-body');
                        const thinkBlock = document.createElement('details');
                        thinkBlock.className = 'msg-thinking';
                        thinkBlock.open = true;
                        thinkBlock.innerHTML = `
                            <summary>Reasoning</summary>
                            <div class="thinking-content"></div>
                        `;
                        // Insert before msg-text
                        const msgText = body.querySelector('.msg-text');
                        body.insertBefore(thinkBlock, msgText);
                    }
                    const thinkContent = currentAssistantEl.querySelector('.thinking-content');
                    if (thinkContent) thinkContent.textContent += data.content;
                    scrollChat();
                }
                break;
            case 'content':
                if (currentAssistantEl) {
                    // Collapse thinking when answer starts
                    if (isInThinking) {
                        isInThinking = false;
                        const thinkBlock = currentAssistantEl.querySelector('.msg-thinking');
                        if (thinkBlock) thinkBlock.open = false;
                        // Remove status
                        const status = currentAssistantEl.querySelector('.msg-status');
                        if (status) status.remove();
                    }
                    const body = currentAssistantEl.querySelector('.msg-text');
                    if (body) body.textContent += data.content;
                    scrollChat();
                }
                break;
            case 'token':
                // Legacy fallback for models that don't separate thinking
                if (currentAssistantEl) {
                    const body = currentAssistantEl.querySelector('.msg-text');
                    if (body) body.textContent += data.content;
                    scrollChat();
                }
                break;
            case 'done':
                if (currentAssistantEl) {
                    isInThinking = false;
                    // Remove status
                    const status = currentAssistantEl.querySelector('.msg-status');
                    if (status) status.remove();

                    // Render markdown in the response
                    const msgText = currentAssistantEl.querySelector('.msg-text');
                    const rawText = msgText.textContent;
                    msgText.innerHTML = renderMarkdown(rawText);

                    // Add sources + search online button
                    const body = currentAssistantEl.querySelector('.msg-body');
                    if (currentAssistantEl._sources && currentAssistantEl._sources.length) {
                        const sourcesDiv = document.createElement('div');
                        sourcesDiv.className = 'msg-sources';
                        currentAssistantEl._sources.forEach(s => {
                            const tag = document.createElement('span');
                            tag.className = 'source-tag';
                            tag.textContent = s.name;
                            sourcesDiv.appendChild(tag);
                        });
                        body.appendChild(sourcesDiv);
                    }

                    // Add "Search Online" button per response
                    const actionsDiv = document.createElement('div');
                    actionsDiv.className = 'msg-actions';
                    actionsDiv.innerHTML = `<button class="btn btn-sm btn-web-search" onclick="App.searchOnlineForResponse(this)">Search Online</button>`;
                    body.appendChild(actionsDiv);
                    // Store in history (answer only, not thinking)
                    chatHistory.push({ role: 'assistant', content: rawText });
                    currentAssistantEl = null;
                }
                break;
            case 'error':
                if (currentAssistantEl) {
                    isInThinking = false;
                    const body = currentAssistantEl.querySelector('.msg-text');
                    body.textContent = `Error: ${data.content}`;
                    body.style.color = 'var(--error)';
                    currentAssistantEl = null;
                }
                break;
        }
    }

    function appendChatMessage(role, text, isStreaming = false) {
        const container = document.getElementById('chat-messages');
        const msg = document.createElement('div');
        msg.className = `chat-msg ${role}`;

        const avatar = role === 'user' ? 'U' : 'A';
        msg.innerHTML = `
            <div class="msg-avatar">${avatar}</div>
            <div class="msg-body">
                <div class="msg-text">${escapeHtml(text)}</div>
                ${isStreaming ? '<div class="msg-status">Thinking...</div>' : ''}
            </div>
        `;

        container.appendChild(msg);
        if (isStreaming) currentAssistantEl = msg;
        scrollChat();
    }

    function updateStreamStatus(text) {
        if (currentAssistantEl) {
            const status = currentAssistantEl.querySelector('.msg-status');
            if (status) status.textContent = text;
        }
    }

    async function fetchChat(text) {
        try {
            const resp = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text, history: chatHistory.slice(-6) }),
            });
            const data = await resp.json();
            appendChatMessage('assistant', data.answer);
            chatHistory.push({ role: 'assistant', content: data.answer });
        } catch (e) {
            appendChatMessage('assistant', `Error: ${e.message}`);
        }
    }

    function scrollChat() {
        const el = document.getElementById('chat-messages');
        el.scrollTop = el.scrollHeight;
    }

    // ── Browse / Filter ─────────────────────────
    async function loadFilters() {
        try {
            const [cats, devs, subcats] = await Promise.all([
                fetch('/api/categories').then(r => r.json()),
                fetch('/api/developers').then(r => r.json()),
                fetch('/api/subcategories').then(r => r.json()),
            ]);

            const catSelect = document.getElementById('filter-category');
            const catList = document.getElementById('category-list');
            cats.forEach(c => {
                const opt = document.createElement('option');
                opt.value = c.category;
                opt.textContent = `${c.category} (${c.count})`;
                catSelect.appendChild(opt);

                // Also populate datalist for edit modal
                if (catList) {
                    const dlOpt = document.createElement('option');
                    dlOpt.value = c.category;
                    catList.appendChild(dlOpt);
                }
            });

            // Populate subcategory datalist for edit modal
            const subcatList = document.getElementById('subcategory-list');
            if (subcatList) {
                subcats.forEach(s => {
                    const opt = document.createElement('option');
                    opt.value = s;
                    subcatList.appendChild(opt);
                });
            }

            const devSelect = document.getElementById('filter-developer');
            devs.forEach(d => {
                const opt = document.createElement('option');
                opt.value = d.developer;
                opt.textContent = `${d.developer} (${d.count})`;
                devSelect.appendChild(opt);
            });
        } catch (e) {
            console.error('Failed to load filters:', e);
        }
    }

    async function loadPlugins(page = 1) {
        currentPage = page;
        const params = new URLSearchParams();
        params.set('page', page);

        const search = document.getElementById('browse-search').value.trim();
        if (search) params.set('search', search);

        const cat = document.getElementById('filter-category').value;
        if (cat) params.set('category', cat);

        const type = document.getElementById('filter-type').value;
        if (type) params.set('plugin_type', type);

        const dev = document.getElementById('filter-developer').value;
        if (dev) params.set('developer', dev);

        const fmt = document.getElementById('filter-format').value;
        if (fmt) params.set('format', fmt);

        if (document.getElementById('filter-own').checked) {
            params.set('is_own', 'true');
        }

        try {
            const resp = await fetch(`/api/plugins?${params}`);
            const data = await resp.json();

            document.getElementById('browse-info').textContent =
                `Showing ${data.plugins.length} of ${data.total} plugins (page ${data.page}/${data.pages})`;

            renderPluginGrid('plugin-list', data.plugins);
            renderPagination('pagination', data.page, data.pages, loadPlugins);
        } catch (e) {
            document.getElementById('plugin-list').innerHTML =
                '<p class="empty-state">Failed to load plugins. Is the server running?</p>';
        }
    }

    function debouncedBrowse() {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => loadPlugins(1), 300);
    }

    // ── Review Tab ──────────────────────────────
    let reviewDebounceTimer = null;

    async function loadReviewPlugins(page = 1) {
        reviewPage = page;
        try {
            const params = new URLSearchParams({ needs_review: 'true', page });
            const search = document.getElementById('review-search')?.value.trim();
            if (search) params.set('search', search);
            const dev = document.getElementById('review-filter-developer')?.value;
            if (dev) params.set('developer', dev);

            const resp = await fetch(`/api/plugins?${params}`);
            const data = await resp.json();
            renderPluginGrid('review-list', data.plugins);
            renderPagination('review-pagination', data.page, data.pages, loadReviewPlugins);

            // Populate developer filter from review plugins
            _populateReviewDevFilter(data.plugins);
        } catch (e) {
            document.getElementById('review-list').innerHTML =
                '<p class="empty-state">Failed to load review queue.</p>';
        }
    }

    function _populateReviewDevFilter(plugins) {
        const select = document.getElementById('review-filter-developer');
        if (!select) return;
        const current = select.value;
        // Only populate once (check if has options beyond default)
        if (select.options.length > 1) return;

        // Fetch all review plugin developers
        fetch('/api/plugins?needs_review=true&per_page=9999')
            .then(r => r.json())
            .then(data => {
                const devs = {};
                (data.plugins || []).forEach(p => {
                    if (p.developer) devs[p.developer] = (devs[p.developer] || 0) + 1;
                });
                const sorted = Object.entries(devs).sort((a, b) => a[0].localeCompare(b[0]));
                sorted.forEach(([dev, count]) => {
                    const opt = document.createElement('option');
                    opt.value = dev;
                    opt.textContent = `${dev} (${count})`;
                    select.appendChild(opt);
                });
                select.value = current;
            });
    }

    function debouncedReview() {
        clearTimeout(reviewDebounceTimer);
        reviewDebounceTimer = setTimeout(() => loadReviewPlugins(1), 300);
    }

    async function loadReviewBadge() {
        try {
            const resp = await fetch('/api/stats');
            const data = await resp.json();
            const badge = document.getElementById('review-badge');
            if (data.needs_review > 0) {
                badge.textContent = data.needs_review;
                badge.classList.remove('hidden');
            }
        } catch (e) { /* ignore */ }
    }

    // ── Stats ───────────────────────────────────
    async function loadStats() {
        try {
            const resp = await fetch('/api/stats');
            const data = await resp.json();

            const container = document.getElementById('stats-container');
            const maxCat = data.top_categories.length ? data.top_categories[0].count : 1;
            const maxDev = data.top_developers.length ? data.top_developers[0].count : 1;

            container.innerHTML = `
                <div class="stat-card">
                    <div class="stat-value">${data.total}</div>
                    <div class="stat-label">Total Plugins</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${data.classified}</div>
                    <div class="stat-label">Classified</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${data.needs_review}</div>
                    <div class="stat-label">Need Review</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${data.own_plugins}</div>
                    <div class="stat-label">Own Plugins</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${data.instruments}</div>
                    <div class="stat-label">Instruments</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${data.effects}</div>
                    <div class="stat-label">Effects</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${data.embeddings_count}</div>
                    <div class="stat-label">Embeddings</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${data.formats.map(f => `${f.format}: ${f.count}`).join(', ')}</div>
                    <div class="stat-label">By Format</div>
                </div>

                <div class="stats-section">
                    <h3>Top Categories</h3>
                    <div class="stat-bar-list">
                        ${data.top_categories.map(c => `
                            <div class="stat-bar-item">
                                <span class="stat-bar-label">${c.category}</span>
                                <div class="stat-bar">
                                    <div class="stat-bar-fill" style="width:${(c.count / maxCat * 100).toFixed(1)}%"></div>
                                </div>
                                <span class="stat-bar-count">${c.count}</span>
                            </div>
                        `).join('')}
                    </div>
                </div>

                <div class="stats-section">
                    <h3>Top Developers</h3>
                    <div class="stat-bar-list">
                        ${data.top_developers.map(d => `
                            <div class="stat-bar-item">
                                <span class="stat-bar-label">${d.developer}</span>
                                <div class="stat-bar">
                                    <div class="stat-bar-fill" style="width:${(d.count / maxDev * 100).toFixed(1)}%"></div>
                                </div>
                                <span class="stat-bar-count">${d.count}</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        } catch (e) {
            document.getElementById('stats-container').innerHTML =
                '<p class="empty-state">Failed to load stats. Run a scan first.</p>';
        }
    }

    // ── Plugin Card Rendering ───────────────────
    function renderPluginGrid(containerId, plugins) {
        const container = document.getElementById(containerId);
        if (!plugins.length) {
            container.innerHTML = '<p class="empty-state">No plugins found. Try adjusting filters or run a scan.</p>';
            return;
        }

        container.innerHTML = plugins.map(p => {
            const ownClass = p.is_own_plugin ? ' own-plugin' : '';
            const conf = p.classification_confidence || 'unclassified';
            const tags = [];
            if (p.category) tags.push(`<span class="meta-tag category">${esc(p.category)}</span>`);
            if (p.plugin_type) tags.push(`<span class="meta-tag type">${esc(p.plugin_type)}</span>`);
            if (p.character) tags.push(`<span class="meta-tag character">${esc(p.character)}</span>`);
            if (p.is_own_plugin) tags.push(`<span class="meta-tag own">${esc(p.own_brand || 'Own')}</span>`);

            const dismissBtn = containerId === 'review-list'
                ? `<button class="btn-dismiss" onclick="event.stopPropagation(); App.dismissPlugin(${p.id})" title="Exclude from enrichment">&times;</button>`
                : '';

            return `
                <div class="plugin-card${ownClass}" onclick="App.openEdit(${p.id})">
                    <div class="plugin-card-header">
                        <span class="plugin-name">
                            <span class="confidence-dot ${conf}" title="${conf}"></span>
                            ${esc(p.display_name || p.name)}
                        </span>
                        <span class="plugin-format">${p.formats ? p.formats.join(' | ') : esc(p.format)}</span>
                        ${dismissBtn}
                    </div>
                    ${p.developer ? `<div class="plugin-developer">${esc(p.developer)}</div>` : ''}
                    ${p.description ? `<div class="plugin-description">${esc(p.description)}</div>` : ''}
                    <div class="plugin-meta">${tags.join('')}</div>
                </div>
            `;
        }).join('');
    }

    function renderPagination(containerId, current, total, callback) {
        const container = document.getElementById(containerId);
        if (total <= 1) { container.innerHTML = ''; return; }

        let html = '';
        if (current > 1) html += `<button onclick="App._paginate(${current - 1}, '${containerId}')">&laquo;</button>`;

        const start = Math.max(1, current - 3);
        const end = Math.min(total, current + 3);

        for (let i = start; i <= end; i++) {
            html += `<button class="${i === current ? 'active' : ''}"
                onclick="App._paginate(${i}, '${containerId}')">${i}</button>`;
        }

        if (current < total) html += `<button onclick="App._paginate(${current + 1}, '${containerId}')">&raquo;</button>`;
        container.innerHTML = html;
    }

    function _paginate(page, containerId) {
        if (containerId === 'review-pagination') {
            loadReviewPlugins(page);
        } else {
            loadPlugins(page);
        }
    }

    // ── Edit Modal ──────────────────────────────
    async function openEdit(pluginId) {
        try {
            const resp = await fetch(`/api/plugins/${pluginId}`);
            const p = await resp.json();

            document.getElementById('edit-id').value = p.id;
            document.getElementById('modal-title').textContent = `Edit: ${p.display_name || p.name}`;

            // Fill form fields
            const fields = [
                'display_name', 'developer', 'plugin_type', 'category',
                'subcategory', 'subtype', 'emulation_of', 'character',
                'signal_chain_position', 'tags', 'description',
                'specialty', 'best_used_for', 'hidden_tips', 'not_ideal_for',
                'notes', 'own_brand',
            ];
            fields.forEach(f => {
                const el = document.getElementById(`edit-${f}`);
                if (el) el.value = p[f] || '';
            });

            // Clear enrich context inputs
            document.getElementById('enrich-url').value = '';
            document.getElementById('enrich-pdf').value = '';
            document.getElementById('enrich-single-status').classList.add('hidden');

            document.getElementById('edit-is_own_plugin').checked = !!p.is_own_plugin;

            // Meta info
            const meta = [];
            if (p.formats) meta.push(p.formats.join(' | '));
            else if (p.format) meta.push(p.format);
            if (p.file_name) meta.push(p.file_name);
            if (p.classification_confidence) meta.push(`Confidence: ${p.classification_confidence}`);
            document.getElementById('edit-meta').textContent = meta.join(' | ');

            document.getElementById('edit-modal').classList.remove('hidden');
        } catch (e) {
            alert('Failed to load plugin details.');
        }
    }

    function closeModal() {
        document.getElementById('edit-modal').classList.add('hidden');
    }

    async function savePlugin(event) {
        event.preventDefault();
        const id = document.getElementById('edit-id').value;

        const fields = [
            'display_name', 'developer', 'plugin_type', 'category',
            'subcategory', 'subtype', 'emulation_of', 'character',
            'signal_chain_position', 'tags', 'description',
            'specialty', 'best_used_for', 'hidden_tips', 'not_ideal_for',
            'notes', 'own_brand',
        ];

        const body = {};
        fields.forEach(f => {
            const el = document.getElementById(`edit-${f}`);
            const val = el ? el.value.trim() : '';
            if (val) body[f] = val;
        });

        body.is_own_plugin = document.getElementById('edit-is_own_plugin').checked;
        body.needs_review = false; // Mark as reviewed upon save

        try {
            const resp = await fetch(`/api/plugins/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await resp.json();
            if (data.status === 'updated') {
                closeModal();
                // Refresh whichever view is active
                const activeTab = document.querySelector('.tab-btn.active').dataset.tab;
                if (activeTab === 'browse') loadPlugins(currentPage);
                if (activeTab === 'review') loadReviewPlugins(reviewPage);
                loadReviewBadge();
            }
        } catch (e) {
            alert('Failed to save changes.');
        }
    }

    // ── Web Search in Chat ───────────────────────
    async function webSearchFromInput() {
        const input = document.getElementById('chat-input');
        const query = input.value.trim();
        if (!query) return;

        // Auto-create conversation if needed
        if (!currentConversationId) {
            await newConversation();
        }

        const welcome = document.querySelector('.chat-welcome');
        if (welcome) welcome.remove();

        // Show user's search query
        appendChatMessage('user', query);
        chatHistory.push({ role: 'user', content: query });
        input.value = '';

        // Show searching status
        appendChatMessage('assistant', '', true);
        const statusEl = currentAssistantEl.querySelector('.msg-status');
        if (statusEl) statusEl.textContent = 'Searching the web...';

        try {
            // Fetch web results
            const resp = await fetch('/api/web-search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query }),
            });
            const data = await resp.json();
            const results = data.results || [];

            // Build web context for the LLM
            const webContext = results.map(r => {
                let text = `${r.title}\n${r.url}\n${r.snippet || ''}`;
                if (r.page_content) text += `\n${r.page_content}`;
                return text;
            }).join('\n\n---\n\n');

            // Now send to LLM with web context
            if (ws && ws.readyState === WebSocket.OPEN) {
                // Remove the placeholder
                if (currentAssistantEl) currentAssistantEl.remove();
                currentAssistantEl = null;

                appendChatMessage('assistant', '', true);
                ws.send(JSON.stringify({
                    message: `Based on these web search results, answer: ${query}`,
                    history: chatHistory.slice(-6),
                    conversation_id: currentConversationId,
                    web_context: webContext,
                }));
            }
        } catch (e) {
            if (currentAssistantEl) {
                const msgText = currentAssistantEl.querySelector('.msg-text');
                msgText.textContent = `Search failed: ${e.message}`;
                currentAssistantEl = null;
            }
        }
        loadConversations();
    }

    async function searchOnlineForResponse(btn) {
        // Extract the last user query from chat history
        const lastUserMsg = chatHistory.filter(m => m.role === 'user').pop();
        if (!lastUserMsg) return;

        btn.disabled = true;
        btn.textContent = 'Searching...';

        try {
            const resp = await fetch('/api/web-search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: lastUserMsg.content }),
            });
            const data = await resp.json();
            const results = data.results || [];

            const webContext = results.map(r => {
                let text = `${r.title}\n${r.url}\n${r.snippet || ''}`;
                if (r.page_content) text += `\n${r.page_content}`;
                return text;
            }).join('\n\n---\n\n');

            // Send a follow-up with web context
            if (ws && ws.readyState === WebSocket.OPEN) {
                appendChatMessage('assistant', '', true);
                ws.send(JSON.stringify({
                    message: `I searched the web for more information about: "${lastUserMsg.content}". Use these web results to give me a more detailed answer.`,
                    history: chatHistory.slice(-6),
                    conversation_id: currentConversationId,
                    web_context: webContext,
                }));
                chatHistory.push({ role: 'user', content: `[Web search: ${lastUserMsg.content}]` });
            }
        } catch (e) {
            btn.textContent = 'Search failed';
        }
    }

    // ── Conversations ──────────────────────────
    async function loadConversations(search = null) {
        try {
            const q = search ? `?search=${encodeURIComponent(search)}` : '';
            const resp = await fetch(`/api/conversations${q}`);
            const convs = await resp.json();
            const list = document.getElementById('conv-list');
            if (!convs.length) {
                list.innerHTML = '<div style="padding:12px;color:var(--text-muted);font-size:var(--font-size-sm)">No conversations yet</div>';
                return;
            }
            list.innerHTML = convs.map(c => {
                const active = c.id === currentConversationId ? ' active' : '';
                const date = new Date(c.updated_at + 'Z').toLocaleDateString();
                return `
                    <div class="conv-item${active}" onclick="App.switchConversation(${c.id})">
                        <span class="conv-item-title">${esc(c.title)}</span>
                        <span class="conv-item-date">${date}</span>
                        <button class="conv-item-delete" onclick="event.stopPropagation(); App.deleteConversation(${c.id})" title="Delete">&times;</button>
                    </div>
                `;
            }).join('');
        } catch (e) {
            console.error('Failed to load conversations:', e);
        }
    }

    async function newConversation() {
        try {
            const resp = await fetch('/api/conversations', { method: 'POST' });
            const conv = await resp.json();
            currentConversationId = conv.id;
            chatHistory = [];
            // Clear chat area
            const msgs = document.getElementById('chat-messages');
            msgs.innerHTML = `
                <div class="chat-welcome">
                    <p>I'm Daedalus -- ask me anything about your plugin collection.</p>
                    <div class="suggestions">
                        <button class="suggestion-chip" onclick="App.sendSuggestion(this)">What compressors do I have?</button>
                        <button class="suggestion-chip" onclick="App.sendSuggestion(this)">Find something warm for vocals</button>
                        <button class="suggestion-chip" onclick="App.sendSuggestion(this)">Which plugins emulate analog hardware?</button>
                        <button class="suggestion-chip" onclick="App.sendSuggestion(this)">Show me my own plugins</button>
                    </div>
                </div>
            `;
            loadConversations();
        } catch (e) {
            console.error('Failed to create conversation:', e);
        }
    }

    async function switchConversation(convId) {
        currentConversationId = convId;
        chatHistory = [];
        try {
            const resp = await fetch(`/api/conversations/${convId}/messages`);
            const messages = await resp.json();
            const msgs = document.getElementById('chat-messages');
            msgs.innerHTML = '';
            messages.forEach(m => {
                if (m.role === 'user') {
                    appendChatMessage('user', m.content);
                    chatHistory.push({ role: 'user', content: m.content });
                } else {
                    appendChatMessage('assistant', m.content);
                    // Render markdown on loaded messages
                    const lastMsg = msgs.querySelector('.chat-msg:last-child .msg-text');
                    if (lastMsg) lastMsg.innerHTML = renderMarkdown(m.content);
                    chatHistory.push({ role: 'assistant', content: m.content });
                }
            });
            if (!messages.length) {
                msgs.innerHTML = `
                    <div class="chat-welcome">
                        <p>I'm Daedalus -- ask me anything about your plugin collection.</p>
                    </div>
                `;
            }
            scrollChat();
            loadConversations();
        } catch (e) {
            console.error('Failed to load conversation:', e);
        }
    }

    async function deleteConversation(convId) {
        try {
            await fetch(`/api/conversations/${convId}`, { method: 'DELETE' });
            if (currentConversationId === convId) {
                currentConversationId = null;
                chatHistory = [];
                document.getElementById('chat-messages').innerHTML = `
                    <div class="chat-welcome">
                        <p>I'm Daedalus -- ask me anything about your plugin collection.</p>
                    </div>
                `;
            }
            loadConversations();
        } catch (e) {
            console.error('Failed to delete conversation:', e);
        }
    }

    function searchConversations() {
        const q = document.getElementById('conv-search').value.trim();
        loadConversations(q || null);
    }

    // ── Dismiss Plugin from Review ────────────────
    async function dismissPlugin(pluginId) {
        try {
            await fetch(`/api/plugins/${pluginId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ needs_review: false }),
            });
            loadReviewPlugins(reviewPage);
            loadReviewBadge();
        } catch (e) {
            console.error('Failed to dismiss plugin:', e);
        }
    }

    // ── Per-Plugin Enrichment ───────────────────
    async function enrichSingle() {
        const id = document.getElementById('edit-id').value;
        if (!id) return;

        // Check if plugin already has enriched data
        const hasData = document.getElementById('edit-description').value.trim()
                     || document.getElementById('edit-character').value.trim()
                     || document.getElementById('edit-specialty').value.trim();

        let force = false;
        if (hasData) {
            const choice = confirm(
                'This plugin already has enrichment data.\n\n' +
                'OK = Replace existing data with fresh research\n' +
                'Cancel = Keep existing data, only fill empty fields'
            );
            force = choice;
        }

        const url = document.getElementById('enrich-url').value.trim() || undefined;
        const pdfPath = document.getElementById('enrich-pdf').value.trim() || undefined;

        const btn = document.getElementById('btn-enrich-single');
        const statusEl = document.getElementById('enrich-single-status');

        btn.disabled = true;
        btn.textContent = 'Enriching...';
        statusEl.textContent = 'Running research agents...';
        statusEl.classList.remove('hidden');

        try {
            const body = { force };
            if (url) body.url = url;
            if (pdfPath) body.pdf_path = pdfPath;

            const resp = await fetch(`/api/plugins/${id}/enrich`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await resp.json();

            if (data.plugin) {
                // Auto-fill empty form fields with enriched data
                const enrichFields = [
                    'developer', 'plugin_type', 'category', 'subcategory',
                    'subtype', 'emulation_of', 'character', 'signal_chain_position',
                    'tags', 'description', 'specialty', 'best_used_for',
                    'hidden_tips', 'not_ideal_for',
                ];
                enrichFields.forEach(f => {
                    const el = document.getElementById(`edit-${f}`);
                    if (el && !el.value && data.plugin[f]) {
                        el.value = data.plugin[f];
                        el.classList.add('enriched-field');
                        setTimeout(() => el.classList.remove('enriched-field'), 3000);
                    }
                });
                statusEl.textContent = 'Enrichment complete. Review and save.';
            } else {
                statusEl.textContent = data.detail || 'Enrichment returned no data.';
            }
        } catch (e) {
            statusEl.textContent = `Error: ${e.message}`;
        } finally {
            btn.disabled = false;
            btn.textContent = 'Enrich';
        }
    }

    // ── Scan ────────────────────────────────────
    async function triggerScan() {
        const btn = document.getElementById('btn-scan');
        const status = document.getElementById('scan-status');

        btn.disabled = true;
        status.textContent = 'Scanning plugin directories...';

        try {
            const resp = await fetch('/api/scan', { method: 'POST' });
            const data = await resp.json();
            let statusText = `Scan complete: ${data.scanned} scanned, ${data.inserted} new, ${data.updated} updated, ${data.embedded} embedded`;
            status.textContent = statusText;

            // Refresh all views
            loadFilters();
            loadStats();
            loadReviewBadge();
            const activeTab = document.querySelector('.tab-btn.active').dataset.tab;
            if (activeTab === 'browse') loadPlugins(1);
            if (activeTab === 'review') loadReviewPlugins(1);

            // Offer to enrich new plugins
            if (data.new_plugin_ids && data.new_plugin_ids.length > 0) {
                const count = data.new_plugin_ids.length;
                const enrich = confirm(
                    `${count} new plugin${count > 1 ? 's' : ''} found!\n\n` +
                    `Do you want to enrich ${count > 1 ? 'them' : 'it'} with web research?\n` +
                    `This will run the AI agents to find descriptions, character, and tips.`
                );
                if (enrich) {
                    // Switch to review tab and start enrichment for new plugins only
                    switchTab('review');
                    _startEnrichmentForIds(data.new_plugin_ids);
                }
            }
        } catch (e) {
            status.textContent = `Scan failed: ${e.message}`;
        } finally {
            btn.disabled = false;
        }
    }

    // ── Enrichment ──────────────────────────────
    let enrichWs = null;

    function _startEnrichmentForIds(pluginIds) {
        // Set default options and trigger enrichment with specific plugin IDs
        document.getElementById('enrich-delay').value = '2';
        document.getElementById('enrich-batch-limit').value = '0';
        _launchEnrichmentWs({ plugin_ids: pluginIds, delay: 2, batch_limit: 0 });
    }

    function startEnrichment() {
        const delay = parseInt(document.getElementById('enrich-delay').value) || 2;
        const batchLimit = parseInt(document.getElementById('enrich-batch-limit').value) || 0;
        _launchEnrichmentWs({ delay, batch_limit: batchLimit });
    }

    function _launchEnrichmentWs(config) {
        const btn = document.getElementById('enrich-btn');
        const pauseBtn = document.getElementById('enrich-pause-btn');
        const cancelBtn = document.getElementById('enrich-cancel-btn');
        const progressEl = document.getElementById('enrich-progress');
        const statusEl = document.getElementById('enrich-status');
        const fillEl = document.getElementById('enrich-progress-fill');

        btn.classList.add('hidden');
        pauseBtn.classList.remove('hidden');
        pauseBtn.textContent = 'Pause';
        cancelBtn.classList.remove('hidden');
        progressEl.classList.remove('hidden');
        statusEl.textContent = 'Connecting...';
        fillEl.style.width = '0%';

        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        enrichWs = new WebSocket(`${proto}//${location.host}/ws/enrich`);

        enrichWs.onopen = () => {
            enrichWs.send(JSON.stringify(config));
        };

        enrichWs.onmessage = (event) => {
            const data = JSON.parse(event.data);
            const stats = data.stats || {};
            const pct = data.total > 0 ? Math.round((data.processed / data.total) * 100) : 0;

            switch (data.type) {
                case 'progress':
                    fillEl.style.width = `${pct}%`;
                    statusEl.textContent =
                        `${data.processed}/${data.total} (${pct}%) — ${data.current || '...'} | enriched: ${stats.enriched || 0}`;
                    break;
                case 'enriched':
                    fillEl.style.width = `${pct}%`;
                    statusEl.textContent =
                        `${data.processed}/${data.total} (${pct}%) — ${data.current || '...'} | enriched: ${stats.enriched || 0}`;
                    // Live-refresh: remove enriched plugins from review list
                    loadReviewPlugins(reviewPage);
                    loadReviewBadge();
                    break;
                case 'error':
                    statusEl.textContent =
                        `${data.processed}/${data.total} — Error: ${data.error || data.current} | enriched: ${stats.enriched || 0}, errors: ${stats.errors || 0}`;
                    break;
                case 'paused':
                    pauseBtn.textContent = 'Resume';
                    statusEl.textContent += ' [PAUSED]';
                    break;
                case 'resumed':
                    pauseBtn.textContent = 'Pause';
                    break;
                case 'auto_paused':
                case 'rate_limited':
                    pauseBtn.textContent = 'Resume';
                    statusEl.textContent = `${data.reason || 'Auto-paused'} (${stats.enriched || 0} enriched so far)`;
                    break;
                case 'cancelling':
                    statusEl.textContent = 'Cancelling...';
                    break;
                case 'cancelled':
                case 'done':
                    fillEl.style.width = '100%';
                    statusEl.textContent =
                        `${data.type === 'cancelled' ? 'Cancelled' : 'Done'}! ${stats.enriched || 0} enriched, ${stats.errors || 0} errors`;
                    _enrichmentDone();
                    break;
            }
        };

        enrichWs.onerror = () => {
            statusEl.textContent = 'Connection error';
            _enrichmentDone();
        };

        enrichWs.onclose = () => {
            _enrichmentDone();
        };
    }

    function _enrichmentDone() {
        const btn = document.getElementById('enrich-btn');
        const pauseBtn = document.getElementById('enrich-pause-btn');
        const cancelBtn = document.getElementById('enrich-cancel-btn');
        btn.classList.remove('hidden');
        pauseBtn.classList.add('hidden');
        cancelBtn.classList.add('hidden');
        enrichWs = null;
        loadReviewPlugins(1);
        loadReviewBadge();
        loadStats();
        loadFilters();
    }

    function pauseEnrichment() {
        if (!enrichWs) return;
        const pauseBtn = document.getElementById('enrich-pause-btn');
        if (pauseBtn.textContent === 'Pause') {
            enrichWs.send(JSON.stringify({ action: 'pause' }));
        } else {
            enrichWs.send(JSON.stringify({ action: 'resume' }));
        }
    }

    function cancelEnrichment() {
        if (!enrichWs) return;
        enrichWs.send(JSON.stringify({ action: 'cancel' }));
    }

    // ── Settings ────────────────────────────────
    const PROVIDER_URLS = {
        ollama: 'http://127.0.0.1:11434',
        euria: '',
        openrouter: 'https://openrouter.ai/api/v1',
        gemini: 'https://generativelanguage.googleapis.com/v1beta/openai',
        openai: 'https://api.openai.com/v1',
        deepseek: 'https://api.deepseek.com',
    };

    const PROVIDER_MODELS = {
        ollama: 'gemma4:26b',
        euria: 'mixtral',
        openrouter: 'openrouter/free',
        gemini: 'gemini-2.5-flash',
        openai: 'gpt-4o-mini',
        deepseek: 'deepseek-chat',
    };

    const PROVIDER_HINTS = {
        ollama: 'Runs locally on your machine. No API key needed.',
        euria: 'Free, Swiss-hosted, GDPR compliant. Get your API key and product ID at <a href="https://www.infomaniak.com/en/hosting/ai-services" target="_blank">infomaniak.com/ai-services</a>. Set Base URL to: https://api.infomaniak.com/1/ai/YOUR_PRODUCT_ID/openai',
        openrouter: 'Free models available globally, no credit card needed. Get key at <a href="https://openrouter.ai/keys" target="_blank">openrouter.ai/keys</a>',
        gemini: 'Free tier NOT available in EU/EEA/UK/Switzerland. Get key at <a href="https://aistudio.google.com" target="_blank">aistudio.google.com</a>',
        openai: 'Pay-per-use. Get key at <a href="https://platform.openai.com/api-keys" target="_blank">platform.openai.com</a>',
        deepseek: 'Very affordable. Get key at <a href="https://platform.deepseek.com" target="_blank">platform.deepseek.com</a>',
        custom: 'Any OpenAI-compatible endpoint. Enter the base URL and API key.',
    };

    async function loadSettings() {
        try {
            const [settings, sysInfo] = await Promise.all([
                fetch('/api/settings').then(r => r.json()),
                fetch('/api/settings/system-info').then(r => r.json()),
            ]);

            // System info
            document.getElementById('system-info-content').innerHTML = `
                <p><strong>${sysInfo.ram_gb}GB RAM</strong> | ${sysInfo.chip} | ${sysInfo.platform}</p>
                <p class="settings-recommendation">${sysInfo.recommendation}</p>
            `;

            // Fill form
            const provider = settings.llm_provider || 'ollama';
            const savedModel = settings.llm_model || PROVIDER_MODELS[provider] || '';
            document.getElementById('set-llm-provider').value = provider;
            document.getElementById('set-llm-url').value = settings.llm_base_url || PROVIDER_URLS[provider] || '';
            document.getElementById('set-llm-key').value = '';
            document.getElementById('set-llm-temp').value = settings.llm_temperature || '0.3';
            document.getElementById('set-llm-temp-val').textContent = settings.llm_temperature || '0.3';

            // Load models then select the saved one
            await _loadModels('llm', provider);
            document.getElementById('set-llm-model').value = savedModel;

            onProviderChange('llm');

            // Agent settings
            if (settings.agent_provider) {
                document.getElementById('set-agent-same').checked = false;
                document.getElementById('agent-settings').classList.remove('hidden');
                document.getElementById('set-agent-provider').value = settings.agent_provider;
                await _loadModels('agent', settings.agent_provider);
                document.getElementById('set-agent-model').value = settings.agent_model || '';
            }

            // Temperature slider
            document.getElementById('set-llm-temp').oninput = (e) => {
                document.getElementById('set-llm-temp-val').textContent = e.target.value;
            };
        } catch (e) {
            console.error('Failed to load settings:', e);
        }
    }

    function onProviderChange(prefix) {
        const provider = document.getElementById(`set-${prefix}-provider`).value;
        const urlEl = document.getElementById(`${prefix}-url-group`);
        const keyEl = document.getElementById(`${prefix}-key-group`);

        // Auto-fill URL
        if (PROVIDER_URLS[provider] !== undefined) {
            document.getElementById(`set-${prefix}-url`).value = PROVIDER_URLS[provider];
        }

        // Show/hide API key field
        if (keyEl) {
            if (provider === 'ollama') {
                keyEl.classList.add('hidden');
            } else {
                keyEl.classList.remove('hidden');
            }
        }

        // Show provider hint
        const hintEl = document.getElementById(`${prefix}-provider-hint`);
        if (hintEl && PROVIDER_HINTS[provider]) {
            hintEl.innerHTML = PROVIDER_HINTS[provider];
        } else if (hintEl) {
            hintEl.innerHTML = '';
        }

        // Fetch available models
        _loadModels(prefix, provider);
    }

    async function _loadModels(prefix, provider) {
        const select = document.getElementById(`set-${prefix}-model`);
        const defaultModel = PROVIDER_MODELS[provider] || '';
        // Agent section has no URL/key fields -- fall back to chat fields or provider defaults
        const baseUrl = document.getElementById(`set-${prefix}-url`)?.value
            || document.getElementById('set-llm-url')?.value
            || PROVIDER_URLS[provider] || '';
        const apiKey = document.getElementById(`set-${prefix}-key`)?.value
            || document.getElementById('set-llm-key')?.value || '';

        // Reset to default while loading
        select.innerHTML = `<option value="${defaultModel}">${defaultModel || 'Loading...'}</option>`;

        try {
            const params = new URLSearchParams({ provider });
            if (baseUrl) params.set('base_url', baseUrl);
            if (apiKey) params.set('api_key', apiKey);

            const resp = await fetch(`/api/settings/models?${params}`);
            const data = await resp.json();
            const models = data.models || [];

            if (models.length) {
                select.innerHTML = models.map(m =>
                    `<option value="${m}" ${m === defaultModel ? 'selected' : ''}>${m}</option>`
                ).join('');
                // If current default isn't in list, add it
                if (defaultModel && !models.includes(defaultModel)) {
                    select.insertAdjacentHTML('afterbegin',
                        `<option value="${defaultModel}" selected>${defaultModel} (default)</option>`);
                }
            } else {
                select.innerHTML = `<option value="${defaultModel}">${defaultModel || 'No models found'}</option>`;
            }
        } catch (e) {
            select.innerHTML = `<option value="${defaultModel}">${defaultModel || 'Error loading models'}</option>`;
        }
    }

    function toggleAgentSettings() {
        const same = document.getElementById('set-agent-same').checked;
        document.getElementById('agent-settings').classList.toggle('hidden', same);
        if (!same) onAgentProviderChange();
    }

    function onAgentProviderChange() {
        const provider = document.getElementById('set-agent-provider').value;
        _loadModels('agent', provider);
    }

    async function testConnection() {
        const resultEl = document.getElementById('test-result');
        resultEl.textContent = 'Testing...';
        resultEl.style.color = 'var(--text-secondary)';

        try {
            const resp = await fetch('/api/settings/test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    provider: document.getElementById('set-llm-provider').value,
                    base_url: document.getElementById('set-llm-url').value,
                    model: document.getElementById('set-llm-model').value,
                    api_key: document.getElementById('set-llm-key').value || undefined,
                }),
            });
            const data = await resp.json();
            if (data.status === 'connected') {
                resultEl.textContent = `Connected: ${data.model} (${data.provider})`;
                resultEl.style.color = 'var(--success)';
            } else {
                resultEl.textContent = `Error: ${data.error}`;
                resultEl.style.color = 'var(--error)';
            }
        } catch (e) {
            resultEl.textContent = `Error: ${e.message}`;
            resultEl.style.color = 'var(--error)';
        }
    }

    async function saveSettings() {
        const resultEl = document.getElementById('save-result');
        const settings = {
            llm_provider: document.getElementById('set-llm-provider').value,
            llm_base_url: document.getElementById('set-llm-url').value,
            llm_model: document.getElementById('set-llm-model').value,
            llm_temperature: document.getElementById('set-llm-temp').value,
        };

        const apiKey = document.getElementById('set-llm-key').value;
        if (apiKey) settings.llm_api_key = apiKey;

        if (!document.getElementById('set-agent-same').checked) {
            const agentProvider = document.getElementById('set-agent-provider').value;
            settings.agent_provider = agentProvider;
            settings.agent_model = document.getElementById('set-agent-model').value;
            settings.agent_base_url = PROVIDER_URLS[agentProvider] || '';
        }

        try {
            await fetch('/api/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings),
            });
            resultEl.textContent = 'Settings saved';
            resultEl.style.color = 'var(--success)';
            setTimeout(() => { resultEl.textContent = ''; }, 3000);
        } catch (e) {
            resultEl.textContent = `Error: ${e.message}`;
            resultEl.style.color = 'var(--error)';
        }
    }

    // ── Scan Directories ────────────────────────
    let currentScanDirs = [];

    const FORMAT_EXTENSIONS = { AU: '.component', VST3: '.vst3' };

    async function loadScanDirs() {
        try {
            const resp = await fetch('/api/settings/scan-dirs');
            currentScanDirs = await resp.json();
            _renderScanDirs();
        } catch (e) {
            console.error('Failed to load scan dirs:', e);
        }
    }

    function _renderScanDirs() {
        const list = document.getElementById('scan-dirs-list');
        if (!currentScanDirs.length) {
            list.innerHTML = '<p class="settings-hint">No directories configured.</p>';
            return;
        }
        list.innerHTML = currentScanDirs.map((d, i) => `
            <div class="scan-dir-row">
                <span class="scan-dir-path">${esc(d.path)}</span>
                <span class="scan-dir-meta">${d.format} | ${d.scope}</span>
                <button class="btn-remove" onclick="App.removeScanDir(${i})" title="Remove">&times;</button>
            </div>
        `).join('');
    }

    function addScanDir() {
        const pathEl = document.getElementById('scan-dir-new-path');
        const formatEl = document.getElementById('scan-dir-new-format');
        const scopeEl = document.getElementById('scan-dir-new-scope');
        const path = pathEl.value.trim();
        if (!path) return;

        const fmt = formatEl.value;
        currentScanDirs.push({
            path: path,
            format: fmt,
            scope: scopeEl.value,
            extension: FORMAT_EXTENSIONS[fmt] || '.component',
        });
        pathEl.value = '';
        _renderScanDirs();
    }

    function removeScanDir(index) {
        currentScanDirs.splice(index, 1);
        _renderScanDirs();
    }

    async function saveScanDirs() {
        const resultEl = document.getElementById('scan-dirs-result');
        try {
            await fetch('/api/settings/scan-dirs', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(currentScanDirs),
            });
            resultEl.textContent = 'Saved';
            resultEl.style.color = 'var(--success)';
            setTimeout(() => { resultEl.textContent = ''; }, 3000);
        } catch (e) {
            resultEl.textContent = `Error: ${e.message}`;
            resultEl.style.color = 'var(--error)';
        }
    }

    async function resetScanDirs() {
        try {
            // Delete the custom setting to fall back to config defaults
            await fetch('/api/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ scan_dirs_reset: true }),
            });
            await loadScanDirs();
            document.getElementById('scan-dirs-result').textContent = 'Reset to defaults';
        } catch (e) {
            console.error('Failed to reset:', e);
        }
    }

    // ── Markdown Rendering ───────────────────────
    function renderMarkdown(text) {
        // Escape HTML first
        let html = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

        // Code blocks (```...```)
        html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');

        // Inline code (`...`)
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

        // Headers (### > ## > #)
        html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
        html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
        html = html.replace(/^# (.+)$/gm, '<h2>$1</h2>');

        // Horizontal rules
        html = html.replace(/^---+$/gm, '<hr>');

        // Bold and italic
        html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

        // Unordered lists (- or *)
        html = html.replace(/^[\s]*[-*] (.+)$/gm, '<li>$1</li>');

        // Ordered lists (1. 2. etc.)
        html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');

        // Wrap consecutive <li> in <ul>
        html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>');

        // Paragraphs: double newlines
        html = html.replace(/\n\n+/g, '</p><p>');
        // Single newlines within paragraphs
        html = html.replace(/\n/g, '<br>');

        // Wrap in paragraph tags
        html = '<p>' + html + '</p>';

        // Clean up empty paragraphs and fix nesting
        html = html.replace(/<p>\s*<\/p>/g, '');
        html = html.replace(/<p>\s*(<h[234]>)/g, '$1');
        html = html.replace(/(<\/h[234]>)\s*<\/p>/g, '$1');
        html = html.replace(/<p>\s*(<ul>)/g, '$1');
        html = html.replace(/(<\/ul>)\s*<\/p>/g, '$1');
        html = html.replace(/<p>\s*(<pre>)/g, '$1');
        html = html.replace(/(<\/pre>)\s*<\/p>/g, '$1');
        html = html.replace(/<p>\s*(<hr>)\s*<\/p>/g, '$1');

        return html;
    }

    // ── Utilities ───────────────────────────────
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    const esc = escapeHtml;

    // ── Boot ────────────────────────────────────
    document.addEventListener('DOMContentLoaded', init);

    // ── Public API ──────────────────────────────
    return {
        switchTab,
        sendMessage,
        sendSuggestion,
        handleChatKey,
        loadPlugins,
        debouncedBrowse,
        debouncedReview,
        openEdit,
        closeModal,
        savePlugin,
        triggerScan,
        startEnrichment,
        dismissPlugin,
        pauseEnrichment,
        cancelEnrichment,
        enrichSingle,
        loadSettings,
        loadScanDirs,
        addScanDir,
        removeScanDir,
        saveScanDirs,
        resetScanDirs,
        onProviderChange,
        toggleAgentSettings,
        onAgentProviderChange,
        testConnection,
        saveSettings,
        webSearchFromInput,
        searchOnlineForResponse,
        newConversation,
        switchConversation,
        deleteConversation,
        searchConversations,
        _paginate,
    };
})();

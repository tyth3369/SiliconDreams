/**
 * SiliconDreams — Client-side JS (v0.8.0)
 * Handles: theme switching, SSE streaming, language switching.
 * Minimal — most interactivity via HTMX.
 */

// ═══════════════════════════════════════════════════════
// Theme
// ═══════════════════════════════════════════════════════

function getTheme() {
    // Read from cookie (set by server or by us)
    var m = document.cookie.match(/(?:^|;\s*)theme=([^;]*)/);
    return (m && m[1]) || 'auto';
}

function setThemeCookie(value) {
    document.cookie = 'theme=' + value + ';path=/;max-age=' + (365 * 24 * 3600) + ';SameSite=Lax';
}

function applyTheme(t) {
    if (t === 'auto') {
        var d = window.matchMedia('(prefers-color-scheme: dark)').matches;
        document.documentElement.setAttribute('data-theme', d ? 'dark' : 'light');
    } else {
        document.documentElement.setAttribute('data-theme', t);
    }
}

function setTheme(t) {
    setThemeCookie(t);
    applyTheme(t);
    // Update toggle button states
    document.querySelectorAll('#theme-toggles .toggle-btn').forEach(function(btn) {
        btn.classList.toggle('active', btn.getAttribute('data-theme') === t);
    });
}

// Initialize
(function() {
    var theme = getTheme();
    applyTheme(theme);
    // Highlight the active toggle
    document.querySelectorAll('#theme-toggles .toggle-btn').forEach(function(btn) {
        btn.classList.toggle('active', btn.getAttribute('data-theme') === theme);
    });
    // Listen for system changes (for auto mode)
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function() {
        if (getTheme() === 'auto') applyTheme('auto');
    });
})();

// ═══════════════════════════════════════════════════════
// Language
// ═══════════════════════════════════════════════════════

// LANG_TEXT injected by server-side template (see index.html)
window._LANG_TEXT = window._LANG_TEXT || {};

function setLang(lang) {
    document.cookie = 'lang=' + lang + ';path=/;max-age=' + (365 * 24 * 3600) + ';SameSite=Lax';

    // Refresh sidebar via HTMX (no full page reload — preserves chat)
    htmx.ajax('GET', '/sidebar?lang=' + lang, {target: '#sidebar-inner', swap: 'innerHTML'});

    // Update HTML lang attribute
    document.documentElement.lang = lang;

    // Update language-dependent text in the main area
    var txt = window._LANG_TEXT[lang] || window._LANG_TEXT['zh'];
    if (txt) {
        var tagline = document.querySelector('.top-tagline');
        if (tagline) tagline.textContent = txt.tagline;

        var btns = document.querySelectorAll('.quick-actions button');
        if (btns.length >= 3) {
            btns[0].textContent = txt.compare;
            btns[1].textContent = txt.tech;
            btns[2].textContent = txt.finance;
        }

        var input = document.querySelector('.chat-input-area input[name="message"]');
        if (input) input.placeholder = txt.placeholder;

        var uploadTitle = document.querySelector('.sidebar-upload-title');
        if (uploadTitle) uploadTitle.textContent = txt.uploadTitle;
        var uploadHint = document.querySelector('.sidebar-upload-hint');
        if (uploadHint) uploadHint.textContent = txt.uploadHint;
        var uploadHelp = document.querySelector('.sidebar-upload-help');
        if (uploadHelp) uploadHelp.textContent = txt.uploadHelp;

        document.querySelectorAll('.citation-panel').forEach(function(panel) {
            var heading = panel.querySelector('.citation-heading');
            var hint = panel.querySelector('.citation-hint');
            var count = panel.querySelectorAll('.citation-item').length;
            if (heading) {
                heading.textContent = lang === 'zh'
                    ? txt.citationHeading + '（' + count + txt.citationCount + '）'
                    : txt.citationHeading + ' (' + count + ')';
            }
            if (hint) hint.textContent = txt.citationHint;
        });

        // Update hidden lang input in chat form
        var langInput = document.querySelector('.chat-input-area input[name="lang"]');
        if (langInput) langInput.value = lang;
    }
}

function renameConversation(event, conversationId, currentTitle) {
    event.preventDefault();
    event.stopPropagation();
    var lang = document.documentElement.lang || 'zh';
    var text = window._LANG_TEXT[lang] || window._LANG_TEXT.zh || {};
    var title = window.prompt(text.renamePrompt || 'Rename', currentTitle);
    if (!title || !title.trim()) return;
    var body = new URLSearchParams({title: title.trim()});
    fetch('/conversations/' + encodeURIComponent(conversationId) + '/rename', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: body.toString()
    }).then(function(response) {
        if (!response.ok) throw new Error('rename failed');
        return response.text();
    }).then(function(html) {
        var list = document.getElementById('conversation-list');
        if (list) {
            list.innerHTML = html;
            htmx.process(list);
        }
    });
}

// ═══════════════════════════════════════════════════════
// SSE Streaming
// ═══════════════════════════════════════════════════════

window._pendingStreams = {};
window._activeStreams = {};

function renderMarkdownSafe(raw) {
    if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') return null;
    return DOMPurify.sanitize(marked.parse(raw));
}

function linkInlineCitations(container) {
    var walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    var nodes = [];
    while (walker.nextNode()) {
        var node = walker.currentNode;
        var parent = node.parentElement;
        if (!parent || parent.closest('code, pre, a, .citation-panel')) continue;
        if (/\[\d+\]/.test(node.nodeValue || '')) nodes.push(node);
    }

    nodes.forEach(function(node) {
        var value = node.nodeValue || '';
        var expression = /\[(\d+)\]/g;
        var match;
        var cursor = 0;
        var fragment = document.createDocumentFragment();
        while ((match = expression.exec(value)) !== null) {
            fragment.appendChild(document.createTextNode(value.slice(cursor, match.index)));
            var sup = document.createElement('sup');
            var link = document.createElement('a');
            link.href = '#';
            link.dataset.citeIndex = match[1];
            link.className = 'inline-cite';
            link.title = 'Jump to source ' + match[1];
            link.textContent = '[' + match[1] + ']';
            sup.appendChild(link);
            fragment.appendChild(sup);
            cursor = expression.lastIndex;
        }
        fragment.appendChild(document.createTextNode(value.slice(cursor)));
        node.parentNode.replaceChild(fragment, node);
    });
}

window._startStream = function(msgId, targetId) {
    // Idempotency guard: skip if already streaming this message
    if (window._activeStreams[msgId]) return;

    var target = document.getElementById(targetId);
    if (!target) return;

    var es = new EventSource('/chat/stream/' + msgId);
    window._activeStreams[msgId] = es;

    es.onmessage = function(e) {
        var data = JSON.parse(e.data);
        if (data.token) {
            // Clear any active status indicators on first token
            var statusEl = target.parentNode.querySelector('.agent-status');
            if (statusEl) {
                statusEl.style.display = 'none';
            }
            target.textContent += data.token;
            // Auto-scroll
            var container = document.getElementById('chat-container');
            if (container) container.scrollTop = container.scrollHeight;
        } else if (data.status === 'tool_start') {
            // Show tool progress indicator
            var statusEl = target.parentNode.querySelector('.agent-status');
            if (!statusEl) {
                statusEl = document.createElement('div');
                statusEl.className = 'agent-status';
                target.parentNode.insertBefore(statusEl, target);
            }
            var item = document.createElement('span');
            item.className = 'agent-status-item agent-status-active';
            item.setAttribute('data-tool', data.tool);
            item.textContent = data.label;
            statusEl.appendChild(item);
            // Auto-scroll
            var container = document.getElementById('chat-container');
            if (container) container.scrollTop = container.scrollHeight;
        } else if (data.status === 'tool_done') {
            // Mark tool as done — stays visible until final answer starts
            var statusEl = target.parentNode.querySelector('.agent-status');
            if (statusEl) {
                var activeItem = statusEl.querySelector('.agent-status-active[data-tool="' + data.tool + '"]');
                if (activeItem) {
                    activeItem.classList.remove('agent-status-active');
                    activeItem.classList.add('agent-status-done');
                    activeItem.textContent = data.label;
                }
            }
        } else if (data.status === 'info' || data.status === 'thinking') {
            // Info/thinking status
            var statusEl = target.parentNode.querySelector('.agent-status');
            if (!statusEl) {
                statusEl = document.createElement('div');
                statusEl.className = 'agent-status';
                target.parentNode.insertBefore(statusEl, target);
            }
            var item = document.createElement('span');
            item.className = 'agent-status-item agent-status-info';
            item.textContent = data.label;
            statusEl.appendChild(item);
        } else if (data.done) {
            // Convert accumulated markdown to HTML for rich rendering
            if (target.textContent) {
                var raw = target.textContent;
                var safeHtml = renderMarkdownSafe(raw);
                if (safeHtml !== null) {
                    target.innerHTML = safeHtml;
                    linkInlineCitations(target);
                    target.style.whiteSpace = 'normal';
                    target.setAttribute('data-rendered', '1');
                }
            }
            es.close();
            delete window._activeStreams[msgId];
        } else if (data.citations) {
            // Inject citation panel after the message content
            var panelHtml = data.panel_html;
            if (panelHtml) {
                var panel = document.createElement('div');
                panel.innerHTML = typeof DOMPurify === 'undefined'
                    ? panelHtml
                    : DOMPurify.sanitize(panelHtml);
                target.parentNode.appendChild(panel.firstElementChild);
            }
        } else if (data.error) {
            target.textContent = data.error;
            es.close();
            delete window._activeStreams[msgId];
        }
    };

    es.onerror = function() {
        es.close();
        delete window._activeStreams[msgId];
    };
};

// After HTMX swaps chat_response, trigger SSE
function initStream() {
    // HTMX just swapped new content — find any pending streams and start them
    for (var msgId in window._pendingStreams) {
        var targetId = window._pendingStreams[msgId];
        window._startStream(msgId, targetId);
        delete window._pendingStreams[msgId];
    }
}

// HTMX event: after a chat POST completes
document.body.addEventListener('htmx:afterSwap', function(evt) {
    if (evt.detail.target.id === 'chat-container') {
        // Give the browser a tick to insert the new elements, then start streams
        setTimeout(initStream, 50);
    }
});

// HTMX event: after upload completes
document.body.addEventListener('htmx:afterSwap', function(evt) {
    if (evt.detail.target.id === 'sidebar-inner') {
        // Re-init theme toggle states after sidebar refresh
        var theme = getTheme();
        document.querySelectorAll('#theme-toggles .toggle-btn').forEach(function(btn) {
            btn.classList.toggle('active', btn.getAttribute('data-theme') === theme);
        });
        syncUploadPolling();
    }
});

// Keep durable PDF ingestion progress current without reloading the page.
window._uploadPollTimer = null;

function syncUploadPolling() {
    var hasActiveJob = document.querySelector('.file-item[data-job-active="true"]');
    if (!hasActiveJob) {
        if (window._uploadPollTimer) {
            clearInterval(window._uploadPollTimer);
            window._uploadPollTimer = null;
        }
        return;
    }
    if (window._uploadPollTimer) return;
    window._uploadPollTimer = setInterval(function() {
        var lang = document.documentElement.lang || 'zh';
        htmx.ajax('GET', '/sidebar?lang=' + lang, {
            target: '#sidebar-inner',
            swap: 'innerHTML'
        });
    }, 1000);
}

// ═══════════════════════════════════════════════════════
// Markdown Rendering (page load)
// ═══════════════════════════════════════════════════════

function renderMarkdownMessages() {
    if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') return;
    document.querySelectorAll('.msg-content').forEach(function(el) {
        if (el.textContent && !el.hasAttribute('data-rendered')) {
            var raw = el.textContent;
            el.innerHTML = renderMarkdownSafe(raw);
            linkInlineCitations(el);
            el.style.whiteSpace = 'normal';
            el.setAttribute('data-rendered', '1');
        }
    });
}

// Run after DOM ready (marked library loaded synchronously before app.js)
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
        renderMarkdownMessages();
        syncUploadPolling();
    });
} else {
    renderMarkdownMessages();
    syncUploadPolling();
}

// ═══════════════════════════════════════════════════════
// Inline Citation Links
// ═══════════════════════════════════════════════════════

// Click handler: open citation <details> panel when inline cite link is clicked
document.addEventListener('click', function(e) {
    var link = e.target.closest('.inline-cite');
    if (link) {
        e.preventDefault();
        var citationIndex = link.getAttribute('data-cite-index');
        var message = link.closest('.chat-msg.assistant');
        if (citationIndex && message) {
            var target = message.querySelector('.citation-item[data-cite-index="' + citationIndex + '"]');
            if (target) {
                // Highlight the target citation item
                target.classList.add('citation-highlight');
                setTimeout(function() {
                    target.classList.remove('citation-highlight');
                }, 2000);

                // Auto-open the parent <details> panel if collapsed
                var details = target.closest('details');
                if (details && !details.open) {
                    details.open = true;
                }
            }
        }
    }
});

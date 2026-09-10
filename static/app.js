/**
 * SiliconDreams — Client-side JS (v0.4.0)
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

        // Update hidden lang input in chat form
        var langInput = document.querySelector('.chat-input-area input[name="lang"]');
        if (langInput) langInput.value = lang;
    }
}

// ═══════════════════════════════════════════════════════
// SSE Streaming
// ═══════════════════════════════════════════════════════

window._pendingStreams = {};
window._activeStreams = {};

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
            if (typeof marked !== 'undefined' && target.textContent) {
                var raw = target.textContent;
                target.innerHTML = marked.parse(raw);
                // Convert [N] to clickable inline citation links
                target.innerHTML = target.innerHTML.replace(
                    /\[(\d+)\]/g,
                    '<sup><a href="#cite-$1" class="inline-cite" title="Jump to source $1">[$1]</a></sup>'
                );
                target.style.whiteSpace = 'normal';
                target.setAttribute('data-rendered', '1');
            }
            es.close();
            delete window._activeStreams[msgId];
        } else if (data.citations) {
            // Inject citation panel after the message content
            var panelHtml = data.panel_html;
            if (panelHtml) {
                var panel = document.createElement('div');
                panel.innerHTML = panelHtml;
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
    }
});

// ═══════════════════════════════════════════════════════
// Markdown Rendering (page load)
// ═══════════════════════════════════════════════════════

function renderMarkdownMessages() {
    if (typeof marked === 'undefined') return;
    document.querySelectorAll('.msg-content').forEach(function(el) {
        if (el.textContent && !el.hasAttribute('data-rendered')) {
            var raw = el.textContent;
            el.innerHTML = marked.parse(raw);
            // Convert [N] to clickable inline citation links
            el.innerHTML = el.innerHTML.replace(
                /\[(\d+)\]/g,
                '<sup><a href="#cite-$1" class="inline-cite" title="Jump to source $1">[$1]</a></sup>'
            );
            el.style.whiteSpace = 'normal';
            el.setAttribute('data-rendered', '1');
        }
    });
}

// Run after DOM ready (marked library loaded synchronously before app.js)
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', renderMarkdownMessages);
} else {
    renderMarkdownMessages();
}

// ═══════════════════════════════════════════════════════
// Inline Citation Links
// ═══════════════════════════════════════════════════════

// Click handler: open citation <details> panel when inline cite link is clicked
document.addEventListener('click', function(e) {
    var link = e.target.closest('.inline-cite');
    if (link) {
        var targetId = link.getAttribute('href');
        if (targetId && targetId.startsWith('#cite-')) {
            var target = document.getElementById(targetId.substring(1));
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

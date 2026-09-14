/**
 * SiliconDreams — Client-side JS (v1.0.0-rc.6)
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
    var secure = location.protocol === 'https:' ? ';Secure' : '';
    document.cookie = 'theme=' + value + ';path=/;max-age=' + (365 * 24 * 3600) + ';SameSite=Lax' + secure;
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
    var secure = location.protocol === 'https:' ? ';Secure' : '';
    document.cookie = 'lang=' + lang + ';path=/;max-age=' + (365 * 24 * 3600) + ';SameSite=Lax' + secure;

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
        if (btns.length >= 5) {
            btns[0].textContent = txt.compare;
            btns[1].textContent = txt.tech;
            btns[2].textContent = txt.finance;
            btns[3].textContent = txt.analytics;
            btns[4].textContent = txt.watchlist;
        }

        var analyticsPanel = document.getElementById('analytics-panel');
        if (analyticsPanel && analyticsPanel.children.length) {
            var workbenchPath = analyticsPanel.querySelector('.watchlist-workbench')
                ? '/watchlist' : '/analytics';
            htmx.ajax('GET', workbenchPath + '?lang=' + lang, {
                target: '#analytics-panel',
                swap: 'innerHTML'
            });
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

function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : '';
}

function renameConversation(conversationId, currentTitle) {
    var lang = document.documentElement.lang || 'zh';
    var text = window._LANG_TEXT[lang] || window._LANG_TEXT.zh || {};
    var title = window.prompt(text.renamePrompt || 'Rename', currentTitle);
    if (!title || !title.trim()) return;
    var body = new URLSearchParams({title: title.trim()});
    fetch('/conversations/' + encodeURIComponent(conversationId) + '/rename', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-CSRF-Token': csrfToken()
        },
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
                statusEl.classList.add('agent-status-hidden');
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
    document.querySelectorAll('[data-stream-msg-id]:not([data-stream-registered])').forEach(function(node) {
        var msgId = node.getAttribute('data-stream-msg-id');
        var targetId = node.getAttribute('data-stream-target-id');
        node.setAttribute('data-stream-registered', 'true');
        window._startStream(msgId, targetId);
    });
}

// HTMX event: after a chat POST completes
document.body.addEventListener('htmx:afterSwap', function(evt) {
    if (evt.detail.target.id === 'chat-container') {
        // Give the browser a tick to insert the new elements, then start streams
        setTimeout(initStream, 50);
    }
});

document.body.addEventListener('htmx:configRequest', function(evt) {
    var token = csrfToken();
    if (token) evt.detail.headers['X-CSRF-Token'] = token;
});

document.body.addEventListener('htmx:afterRequest', function(evt) {
    if (evt.detail.elt && evt.detail.elt.matches('[data-chat-form]') && evt.detail.successful) {
        evt.detail.elt.reset();
        initStream();
    }
});

document.body.addEventListener('htmx:afterSwap', function(evt) {
    if (evt.detail.target.id === 'analytics-panel') renderAnalytics();
});

// ═══════════════════════════════════════════════════════
// Evidence-backed analytics
// ═══════════════════════════════════════════════════════

var SVG_NS = 'http://www.w3.org/2000/svg';

function svgNode(tag, attrs, text) {
    var node = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs || {}).forEach(function(key) { node.setAttribute(key, attrs[key]); });
    if (text !== undefined) node.textContent = text;
    return node;
}

function chartFrame(title) {
    var svg = svgNode('svg', {
        viewBox: '0 0 760 250', role: 'img', 'aria-label': title,
        preserveAspectRatio: 'xMidYMid meet'
    });
    svg.appendChild(svgNode('title', {}, title));
    return svg;
}

function addLegend(svg, series) {
    series.forEach(function(item, index) {
        var x = 52 + index * 130;
        svg.appendChild(svgNode('line', {
            x1: x, y1: 16, x2: x + 20, y2: 16,
            class: 'chart-series-' + index, 'stroke-width': 3
        }));
        svg.appendChild(svgNode('text', {x: x + 27, y: 20, class: 'chart-label'}, item.company_en));
    });
}

function renderLineChart(container, series, metric) {
    var svg = chartFrame(metric);
    var left = 52, right = 738, top = 34, bottom = 212;
    var values = [];
    series.forEach(function(item) {
        item.points.forEach(function(point) { values.push(Number(point.value)); });
    });
    var min = metric === 'gross_margin_pct' ? Math.max(0, Math.floor(Math.min.apply(null, values) / 10) * 10 - 10) : 0;
    var max = Math.ceil(Math.max.apply(null, values) / 10) * 10;
    if (max === min) max = min + 1;
    addLegend(svg, series);

    for (var grid = 0; grid <= 4; grid++) {
        var y = top + (bottom - top) * grid / 4;
        var label = max - (max - min) * grid / 4;
        svg.appendChild(svgNode('line', {x1: left, y1: y, x2: right, y2: y, class: 'chart-grid'}));
        svg.appendChild(svgNode('text', {x: left - 8, y: y + 4, class: 'chart-axis', 'text-anchor': 'end'}, label.toFixed(0)));
    }

    series.forEach(function(item, seriesIndex) {
        var coords = item.points.map(function(point, index) {
            var x = left + (right - left) * index / (item.points.length - 1);
            var y = bottom - (Number(point.value) - min) / (max - min) * (bottom - top);
            return {x: x, y: y, point: point};
        });
        svg.appendChild(svgNode('polyline', {
            points: coords.map(function(p) { return p.x + ',' + p.y; }).join(' '),
            class: 'chart-line chart-series-' + seriesIndex
        }));
        coords.forEach(function(coord) {
            var link = svgNode('a', {
                href: coord.point.source_url, target: '_blank', rel: 'noopener noreferrer',
                'aria-label': item.company_en + ' ' + coord.point.period + ': ' + coord.point.value + '. ' + coord.point.source_title
            });
            var circle = svgNode('circle', {
                cx: coord.x, cy: coord.y, r: 4,
                class: 'chart-point chart-series-' + seriesIndex
            });
            circle.appendChild(svgNode('title', {}, item.company_en + ' · ' + coord.point.period + ' · ' + coord.point.value + '\n' + coord.point.source_title));
            link.appendChild(circle);
            svg.appendChild(link);
        });
    });

    series[0].points.forEach(function(point, index) {
        if (index % 2 !== 0 && index !== series[0].points.length - 1) return;
        var x = left + (right - left) * index / (series[0].points.length - 1);
        svg.appendChild(svgNode('text', {x: x, y: 235, class: 'chart-axis', 'text-anchor': 'middle'}, point.period.replace('20', '')));
    });
    container.replaceChildren(svg);
}

function renderStackedChart(container, companies) {
    var svg = chartFrame('FY2025 process revenue mix');
    companies.forEach(function(company, companyIndex) {
        var y = 65 + companyIndex * 92;
        svg.appendChild(svgNode('text', {x: 20, y: y + 15, class: 'chart-label'}, company.company_en));
        var offset = 105;
        company.segments.forEach(function(segment, segmentIndex) {
            var width = segment.value * 6.1;
            var rect = svgNode('rect', {
                x: offset, y: y, width: width, height: 30,
                class: 'chart-segment chart-segment-' + segmentIndex
            });
            rect.appendChild(svgNode('title', {}, segment.label + ': ' + (segment.approximate ? '~' : '') + segment.value + '%'));
            svg.appendChild(rect);
            if (width > 70) {
                svg.appendChild(svgNode('text', {x: offset + width / 2, y: y + 20, class: 'chart-segment-label', 'text-anchor': 'middle'}, segment.value + '%'));
            }
            svg.appendChild(svgNode('text', {x: offset, y: y + 49, class: 'chart-axis'}, segment.label));
            offset += width;
        });
    });
    container.replaceChildren(svg);
}

function renderBarChart(container, companies) {
    var svg = chartFrame('FY2025 capex intensity');
    companies.forEach(function(company, index) {
        var y = 66 + index * 85;
        svg.appendChild(svgNode('text', {x: 22, y: y + 20, class: 'chart-label'}, company.company_en));
        svg.appendChild(svgNode('rect', {x: 110, y: y, width: company.value * 6.4, height: 32, class: 'chart-bar chart-series-' + index}));
        svg.appendChild(svgNode('text', {x: 120 + company.value * 6.4, y: y + 21, class: 'chart-value'}, company.value.toFixed(1) + '%'));
    });
    container.replaceChildren(svg);
}

function renderAnalytics() {
    var dataNode = document.getElementById('analytics-data');
    if (!dataNode) return;
    var data;
    try { data = JSON.parse(dataNode.textContent); } catch (_error) { return; }
    document.querySelectorAll('#analytics-panel [data-chart="line"]').forEach(function(container) {
        var metric = container.getAttribute('data-metric');
        renderLineChart(container, data.quarterly[metric], metric);
    });
    var stacked = document.querySelector('#analytics-panel [data-chart="stacked"]');
    if (stacked) renderStackedChart(stacked, data.process_mix);
    var bars = document.querySelector('#analytics-panel [data-chart="bars"]');
    if (bars) renderBarChart(bars, data.capex_intensity);
}

document.addEventListener('click', function(event) {
    var languageButton = event.target.closest('[data-set-lang]');
    if (languageButton) {
        setLang(languageButton.getAttribute('data-set-lang'));
        return;
    }
    var themeButton = event.target.closest('#theme-toggles [data-theme]');
    if (themeButton) {
        setTheme(themeButton.getAttribute('data-theme'));
        return;
    }
    var renameButton = event.target.closest('[data-rename-conversation]');
    if (renameButton) {
        event.preventDefault();
        event.stopPropagation();
        renameConversation(
            renameButton.getAttribute('data-rename-conversation'),
            renameButton.getAttribute('data-current-title') || ''
        );
        return;
    }
    if (event.target.closest('[data-logout]')) {
        fetch('/logout', {method: 'POST', headers: {'X-CSRF-Token': csrfToken()}})
            .then(function() { location.assign('/login'); });
        return;
    }
    if (event.target.closest('[data-close-analytics]')) {
        var panel = document.getElementById('analytics-panel');
        if (panel) panel.replaceChildren();
    }
});

document.addEventListener('change', function(event) {
    if (event.target.matches('[data-auto-submit]') && event.target.form) {
        event.target.form.requestSubmit();
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

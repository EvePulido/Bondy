function showTab(btn, panelId) {
    const card = btn.closest('.card');
    card.querySelectorAll('.tab-btn').forEach(b => {
        b.classList.remove('active');
        b.setAttribute('aria-selected', 'false');
    });
    card.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    btn.setAttribute('aria-selected', 'true');
    document.getElementById(panelId).classList.add('active');
}

// ── Card Accordions and Interactive Collapses (Bootstrap 5 Collapse API) ──
document.addEventListener('DOMContentLoaded', () => {
    const card1 = document.querySelector('.card:first-of-type');
    const card2CollapseEl = document.getElementById('card-analyze-collapse');
    let card2Collapse = null;

    if (card2CollapseEl) {
        card2Collapse = new bootstrap.Collapse(card2CollapseEl, { toggle: false });
    }

    // Helper to open Card 2 collapse
    function openCard2() {
        if (card2Collapse) {
            card2Collapse.show();
        }
    }

    if (card1) {
        // Radio button selection visual check styles & auto-open Card 2
        card1.querySelectorAll('.radio-group input[type="radio"]').forEach(radio => {
            radio.addEventListener('change', () => {
                card1.querySelectorAll('.radio-label').forEach(label => {
                    label.classList.remove('checked');
                });
                if (radio.checked) {
                    radio.closest('.radio-label').classList.add('checked');
                    openCard2();
                }
            });
        });

        // Path input change listener to auto-open Card 2
        const pathInput = document.getElementById('path-input');
        if (pathInput) {
            pathInput.addEventListener('input', () => {
                if (pathInput.value.trim() !== '') {
                    openCard2();
                }
            });
        }

        // HTML textarea input listener to auto-open Card 2
        const htmlInput = document.getElementById('html-input');
        if (htmlInput) {
            htmlInput.addEventListener('input', () => {
                if (htmlInput.value.trim() !== '') {
                    openCard2();
                }
            });
        }

        // Theme Selector interaction
        const themeDropdownBtn = document.getElementById('themeDropdown');
        if (themeDropdownBtn) {
            const themeBtnIcon = themeDropdownBtn.querySelector('.theme-icon');
            const themeBtnText = themeDropdownBtn.querySelector('.theme-text');
            const themeSelectorItems = document.querySelectorAll('.theme-selector .dropdown-item');

            themeSelectorItems.forEach(item => {
                item.addEventListener('click', () => {
                    themeSelectorItems.forEach(i => i.classList.remove('active'));
                    item.classList.add('active');

                    // Extract icon name and text span
                    const selectedIcon = item.querySelector('.material-symbols-outlined').textContent.trim();
                    const selectedText = item.querySelector('span:not(.material-symbols-outlined)').textContent.trim();

                    if (themeBtnIcon) {
                        themeBtnIcon.textContent = selectedIcon;
                    }
                    if (themeBtnText) {
                        themeBtnText.textContent = selectedText;
                    }
                    const selectedTheme = item.getAttribute('data-theme-value');
                    document.documentElement.setAttribute('data-theme', selectedTheme);
                });
            });
        }

        // Permitir activar las cabeceras colapsables mediante Enter o Espacio
        document.querySelectorAll('.card-header').forEach(header => {
            header.addEventListener('keydown', (e) => {
                if (e.key === ' ' || e.key === 'Enter') {
                    e.preventDefault();
                    header.click();
                }
            });
        });
    }
});

// ── API Synchronization & Auditor Logic ──

async function runAudit() {
    // 1. Identify which tab is active and grab inputs
    const activeTabPane = document.querySelector('.tab-content .tab-pane.active');
    if (!activeTabPane) {
        alert('Please select a source tab.');
        return;
    }

    let source = '';
    let rawHtml = null;
    let sourceName = '';

    if (activeTabPane.id === 'tab-demo') {
        const checkedRadio = document.querySelector('input[name="demo"]:checked');
        if (checkedRadio) {
            source = checkedRadio.value;
            const labelEl = checkedRadio.closest('.radio-label');
            sourceName = labelEl ? labelEl.querySelector('.site-name').textContent.trim() : source;
        } else {
            alert('Please select a demo site.');
            return;
        }
    } else if (activeTabPane.id === 'tab-path') {
        source = document.getElementById('path-input').value.trim();
        if (!source) {
            alert('Please enter a local file or directory path.');
            return;
        }
        sourceName = source;
    } else if (activeTabPane.id === 'tab-html') {
        source = 'raw_html';
        rawHtml = document.getElementById('html-input').value.trim();
        if (!rawHtml) {
            alert('Please paste raw HTML markup.');
            return;
        }
        sourceName = 'Raw HTML Content';
    }

    // 2. Read selected checks (checkbox parameterization)
    const checkedBoxes = Array.from(document.querySelectorAll('input[name="analyze"]:checked')).map(cb => cb.value);
    if (checkedBoxes.length === 0) {
        alert('Please select at least one test category to analyze.');
        return;
    }

    const enabledChecks = [];
    if (checkedBoxes.includes('images')) enabledChecks.push('WCAG 1.1.1');
    if (checkedBoxes.includes('forms')) enabledChecks.push('WCAG 1.3.1');
    if (checkedBoxes.includes('keyboard')) enabledChecks.push('WCAG 2.4.4');
    if (checkedBoxes.includes('contrast')) {
        enabledChecks.push('WCAG 1.4.3');
        enabledChecks.push('WCAG 3.1.1');
    }

    // Hide configuration screen
    const configScreen = document.getElementById('config-screen');
    if (configScreen) {
        configScreen.style.setProperty('display', 'none', 'important');
    }

    const dynamicScreen = document.getElementById('dynamic-screen');
    dynamicScreen.innerHTML = '';

    // Create steps based on enabled checkboxes
    const stepsToRun = [];
    if (checkedBoxes.includes('images')) {
        stepsToRun.push({ 
            id: 'step-images', 
            pendingText: 'Images',
            activeText: 'Analyzing images...', 
            completedText: 'Images analyzed' 
        });
    }
    if (checkedBoxes.includes('forms')) {
        stepsToRun.push({ 
            id: 'step-forms', 
            pendingText: 'Forms',
            activeText: 'Analyzing forms...', 
            completedText: 'Forms analyzed' 
        });
    }
    if (checkedBoxes.includes('keyboard')) {
        stepsToRun.push({ 
            id: 'step-keyboard', 
            pendingText: 'Keyboard focus',
            activeText: 'Checking keyboard focus...', 
            completedText: 'Keyboard focus checked' 
        });
    }
    if (checkedBoxes.includes('contrast')) {
        stepsToRun.push({ 
            id: 'step-doc', 
            pendingText: 'Contrast & structure',
            activeText: 'Analyzing text contrast...', 
            completedText: 'Contrast analyzed' 
        });
    }

    let stepsHtml = '';
    stepsToRun.forEach(step => {
        stepsHtml += `
            <div class="step-item" id="${step.id}">
                <div style="display: flex; align-items: center; gap: 12px;">
                    <span class="material-symbols-outlined step-icon" aria-hidden="true" style="font-size: 20px; flex-shrink: 0; vertical-align: middle;">pending</span>
                    <span class="step-name" style="font-size: 14.5px; font-weight: 700; color: var(--text-color);">${escapeHtml(step.pendingText)}</span>
                </div>
                <span class="step-badge pending">Pending</span>
            </div>
        `;
    });

    // Inject Loader UI
    dynamicScreen.innerHTML = `
        <div class="running-wrap" style="margin: 20px auto 0; width: 100%;">
            <div class="card">
                <div class="card-content-wrap" style="padding: 32px 24px;">
                    <div class="loader-grid">
                        <!-- Left Column: Spinner & Text -->
                        <div style="display: flex; flex-direction: column; align-items: center; text-align: center; gap: 16px;">
                            <div class="loader-spinner">
                                <span class="custom-spinner"></span>
                            </div>
                            <div>
                                <div class="running-title" style="font-size: 1.25rem; font-weight: 700; color: var(--text-color);">Running accessibility audit…</div>
                                <div class="running-sub" style="font-size: 0.95rem; color: var(--text-muted); margin-top: 4px;">${escapeHtml(sourceName)}</div>
                            </div>
                        </div>
                        
                        <!-- Right Column: Steps -->
                        <div class="progress-steps-list" style="width: 100%; display: flex; flex-direction: column; gap: 12px; margin: 0;">
                            ${stepsHtml}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Function to update step visual state
    function setStepState(stepId, state, message = '') {
        const stepEl = document.getElementById(stepId);
        if (!stepEl) return;
        const iconEl = stepEl.querySelector('.step-icon');
        const nameEl = stepEl.querySelector('.step-name');
        const badgeEl = stepEl.querySelector('.step-badge');
        const stepData = stepsToRun.find(s => s.id === stepId);

        stepEl.classList.remove('active', 'completed');
        badgeEl.className = 'step-badge';

        if (state === 'running') {
            stepEl.classList.add('active');
            if (nameEl && stepData) nameEl.textContent = stepData.activeText;
            if (iconEl) iconEl.textContent = 'sync';
            badgeEl.textContent = 'Scanning…';
            badgeEl.classList.add('running');
        } else if (state === 'completed') {
            stepEl.classList.add('completed');
            if (nameEl && stepData) nameEl.textContent = stepData.completedText;
            if (iconEl) iconEl.textContent = 'check_circle';
            badgeEl.textContent = message || 'Done';
            badgeEl.classList.add('completed');
        } else {
            if (nameEl && stepData) nameEl.textContent = stepData.pendingText;
            if (iconEl) iconEl.textContent = 'pending';
            badgeEl.textContent = 'Pending';
            badgeEl.classList.add('pending');
        }
    }

    // Run sequential steps animation
    let currentStepIdx = 0;
    const animateNextStep = () => {
        if (currentStepIdx < stepsToRun.length) {
            setStepState(stepsToRun[currentStepIdx].id, 'running');
            if (currentStepIdx > 0) {
                setStepState(stepsToRun[currentStepIdx - 1].id, 'completed');
            }
            currentStepIdx++;
        }
    };

    animateNextStep();
    const stepInterval = setInterval(animateNextStep, 1300);

    function fastForwardSteps() {
        clearInterval(stepInterval);
        stepsToRun.forEach(step => {
            setStepState(step.id, 'completed');
        });
    }

    // 3. Fire API request
    try {
        const response = await fetch('/api/audit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                source: source,
                raw_html: rawHtml,
                enabled_checks: enabledChecks
            })
        });

        const data = await response.json();
        fastForwardSteps();

        // Pause briefly for smooth visual transition
        await new Promise(r => setTimeout(r, 600));
        dynamicScreen.innerHTML = '';

        if (data.status === 'success') {
            const fixes = data.data || [];
            
            // Map and classify findings
            let criticalCount = 0;
            let warningCount = 0;

            const classifiedFixes = fixes.map(fix => {
                const info = classifyFinding(fix);
                if (info.severity === 'critical') criticalCount++;
                if (info.severity === 'warning') warningCount++;
                return { ...fix, ...info };
            });

            // Calculate scoring details
            const baseChecksCount = checkedBoxes.length * 10;
            const passedCount = Math.max(0, baseChecksCount - criticalCount - warningCount);
            const score = fixes.length === 0 ? 100 : Math.max(0, 100 - (criticalCount * 15 + warningCount * 7));

            const circumference = 2 * Math.PI * 38; // Radius 38, ~238.76
            const dashLength = (score / 100) * circumference;
            const strokeDashArray = `${dashLength.toFixed(1)} ${circumference.toFixed(1)}`;

            // Build checkboxes badges
            let pillsHtml = '';
            checkedBoxes.forEach(box => {
                let label = box.charAt(0).toUpperCase() + box.slice(1);
                if (box === 'contrast') label = 'Contrast & Structure';
                pillsHtml += `<span class="pill">${escapeHtml(label)}</span> `;
            });

            // Build findings accordion items
            let findingsHtml = '';
            if (classifiedFixes.length === 0) {
                findingsHtml = `
                    <div class="text-center py-5" style="border: 2px solid var(--border-color); border-radius: 20px; background: var(--card-bg);">
                        <span class="material-symbols-outlined text-success" style="font-size: 56px; color: #10b981;">check_circle</span>
                        <h3 class="mt-3" style="font-weight: 700; color: var(--text-color);">No issues found! 🎉</h3>
                        <p class="text-muted" style="color: var(--text-muted);">The selected files meet the configured accessibility criteria.</p>
                    </div>
                `;
            } else {
                classifiedFixes.forEach((fix, idx) => {
                    findingsHtml += `
                        <div class="card" style="border-radius: 20px; margin-bottom: 12px; overflow: hidden;">
                            <div class="finding-header" onclick="toggleFinding(this)" role="button" tabindex="0">
                                <svg class="chevron closed" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                                    <polyline points="6 9 12 15 18 9" />
                                </svg>
                                <span class="badge wcag">${escapeHtml(fix.wcag)}</span>
                                <span class="badge ${escapeHtml(fix.severity)}">${escapeHtml(fix.severity.charAt(0).toUpperCase() + fix.severity.slice(1))}</span>
                                <span class="finding-title" title="${escapeHtml(fix.title)}">${escapeHtml(fix.title)}</span>
                                <span class="finding-agent">${escapeHtml(fix.agent)}</span>
                            </div>
                            <div class="finding-body" style="display: none;">
                                <p class="finding-desc">${escapeHtml(fix.desc)}</p>
                                <div class="code-grid">
                                    <div class="code-block-wrap">
                                        <div class="code-head">
                                            <span class="code-label old">Original — Error</span>
                                            <button class="btn-sec btn-copy" onclick="event.stopPropagation(); copyText(\`${escapeDoubleBackticks(fix.before)}\`, this)">Copy</button>
                                        </div>
                                        <pre class="code-box before"><code>${escapeHtml(fix.before)}</code></pre>
                                    </div>
                                    <div class="code-block-wrap">
                                        <div class="code-head">
                                            <span class="code-label new">Suggested Fix</span>
                                            <button class="btn-sec btn-copy" onclick="event.stopPropagation(); copyText(\`${escapeDoubleBackticks(fix.after)}\`, this)">Copy</button>
                                        </div>
                                        <pre class="code-box after"><code>${escapeHtml(fix.after)}</code></pre>
                                    </div>
                                </div>
                                <div class="fix-explanation" style="margin-top: 8px;">
                                    <strong>Explanation:</strong> ${escapeHtml(fix.explanation)}
                                </div>
                                <button class="btn-apply" onclick="event.stopPropagation(); applyFix(\`${escapeDoubleBackticks(fix.after)}\`, this)">
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle; margin-right:6px;">
                                        <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
                                    </svg>
                                    Apply Fix
                                </button>
                            </div>
                        </div>
                    `;
                });
            }

            // Inject Results screen
            dynamicScreen.innerHTML = `
                <div class="results-container" style="max-width: 860px; margin: 0 auto; padding-bottom: 60px;">
                    <div class="stack" style="display: flex; flex-direction: column; gap: 20px;">
                        
                        <!-- Config summary strip -->
                        <div class="summary-strip">
                            <div class="strip-info">
                                <span class="strip-label">Audited:</span>
                                <span class="strip-value">${escapeHtml(sourceName)}</span>
                                <span class="strip-dot">·</span>
                                ${pillsHtml}
                            </div>
                            <button class="btn-sec" onclick="resetToConfigure()">
                                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="vertical-align: middle; margin-right: 4px;">
                                    <polyline points="1 4 1 10 7 10" />
                                    <path d="M3.51 15a9 9 0 1 0 .49-3.36" />
                                </svg>
                                New audit
                            </button>
                        </div>

                        <!-- Summary widget -->
                        <div class="card card-pad" style="padding: 24px; border-radius: 20px;">
                            <div class="section-label" style="margin-bottom: 16px;">Audit Summary</div>
                            <div class="summary-widget">
                                <div class="score-ring">
                                    <svg width="96" height="96" viewBox="0 0 96 96">
                                        <circle cx="48" cy="48" r="38" fill="none" stroke="var(--border-color)" stroke-width="9" />
                                        <circle cx="48" cy="48" r="38" fill="none" stroke="var(--primary-color)" stroke-width="9"
                                            stroke-linecap="round" stroke-dasharray="${strokeDashArray}" transform="rotate(-90 48 48)" />
                                    </svg>
                                    <div class="score-inner">
                                        <span class="score-num">${score}%</span>
                                        <span class="score-lbl">score</span>
                                    </div>
                                </div>
                                <div class="stat-grid">
                                    <div class="stat-card critical">
                                        <div class="stat-head">
                                            <svg class="stat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                                <circle cx="12" cy="12" r="10" />
                                                <line x1="12" y1="8" x2="12" y2="12" />
                                                <line x1="12" y1="16" x2="12.01" y2="16" />
                                            </svg>
                                            <span>Critical</span>
                                        </div>
                                        <div class="stat-num">${criticalCount}</div>
                                        <div class="stat-sub">errors</div>
                                    </div>
                                    <div class="stat-card warning">
                                        <div class="stat-head">
                                            <svg class="stat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                                                <line x1="12" y1="9" x2="12" y2="13" />
                                                <line x1="12" y1="17" x2="12.01" y2="17" />
                                            </svg>
                                            <span>Warnings</span>
                                        </div>
                                        <div class="stat-num">${warningCount}</div>
                                        <div class="stat-sub">warnings</div>
                                    </div>
                                    <div class="stat-card passed">
                                        <div class="stat-head">
                                            <svg class="stat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                                            </svg>
                                            <span>Passed</span>
                                        </div>
                                        <div class="stat-num">${passedCount}</div>
                                        <div class="stat-sub">checks</div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Findings -->
                        <div>
                            <div class="section-label" style="padding: 0 4px 4px; margin-bottom: 12px;">Findings — ${classifiedFixes.length} issue${classifiedFixes.length !== 1 ? 's' : ''}</div>
                            <div class="stack-sm" style="display: flex; flex-direction: column; gap: 12px;">
                                ${findingsHtml}
                            </div>
                        </div>
                    </div>
                </div>
            `;

            // Setup keyboard navigation support on dynamic finding headers
            document.querySelectorAll('.finding-header').forEach(header => {
                header.addEventListener('keydown', (e) => {
                    if (e.key === ' ' || e.key === 'Enter') {
                        e.preventDefault();
                        header.click();
                    }
                });
            });

        } else {
            // Audit request error UI
            dynamicScreen.innerHTML = `
                <div class="results-container" style="max-width: 600px; margin: 40px auto; text-align: center;">
                    <div class="card card-pad" style="padding: 40px; border-radius: 20px;">
                        <span class="material-symbols-outlined text-danger" style="font-size: 56px; color: #dc2626;">error</span>
                        <h3 class="mt-3 text-danger" style="font-weight: 700; color: #dc2626;">Audit Failed</h3>
                        <p class="text-muted" style="margin: 16px 0; line-height:1.6;">${escapeHtml(data.message)}</p>
                        <button class="btn-primary" onclick="resetToConfigure()" style="max-width:200px; margin: 0 auto;">
                            Try Again
                        </button>
                    </div>
                </div>
            `;
        }
    } catch (error) {
        clearInterval(stepInterval);
        alert('Failed to connect to the server.');
        resetToConfigure();
    }
}

// ── Screen and Finding Navigation Helpers ──

function resetToConfigure() {
    // Clear dynamic screen content
    const dynamicScreen = document.getElementById('dynamic-screen');
    if (dynamicScreen) dynamicScreen.innerHTML = '';

    // Show config screen
    const configScreen = document.getElementById('config-screen');
    if (configScreen) {
        configScreen.style.display = 'block';
    }
}

function toggleFinding(header) {
    const card = header.closest('.card');
    const body = card.querySelector('.finding-body');
    const chevron = header.querySelector('.chevron');
    if (body) {
        const isCollapsed = body.style.display === 'none' || !body.style.display;
        body.style.display = isCollapsed ? 'flex' : 'none';
        if (isCollapsed) {
            chevron.classList.remove('closed');
            chevron.classList.add('open');
        } else {
            chevron.classList.remove('open');
            chevron.classList.add('closed');
        }
    }
}

async function copyText(text, btn) {
    try {
        await navigator.clipboard.writeText(text);
        const originalText = btn.innerHTML;
        btn.innerHTML = 'Copied!';
        btn.classList.add('btn-success');
        setTimeout(() => {
            btn.innerHTML = originalText;
            btn.classList.remove('btn-success');
        }, 1500);
    } catch (err) {
        console.error('Failed to copy: ', err);
    }
}

async function applyFix(text, btn) {
    try {
        await navigator.clipboard.writeText(text);
        const originalText = btn.innerHTML;
        btn.innerHTML = `<span class="material-symbols-outlined" style="font-size:16px;vertical-align:middle;">check</span> Fix Copied!`;
        btn.classList.add('btn-success');
        setTimeout(() => {
            btn.innerHTML = originalText;
            btn.classList.remove('btn-success');
        }, 2000);
    } catch (err) {
        console.error('Failed to copy: ', err);
    }
}

function classifyFinding(fix) {
    const id = (fix.finding_id || '').toLowerCase();
    const exp = (fix.explanation || '').toLowerCase();
    const before = (fix.before || '').toLowerCase();

    let wcag = '1.1.1';
    let severity = 'critical';
    let title = 'Accessibility issue detected';
    let agent = 'AccessibilityAuditor';
    let desc = 'The element does not conform to the WCAG guidelines.';

    if (id.includes('img') || id.includes('alt') || before.includes('<img') || exp.includes('alt text') || exp.includes('image')) {
        wcag = '1.1.1';
        severity = 'critical';
        title = 'Image missing alternative text';
        agent = 'ImageAuditor';
        desc = 'Non-decorative images must have descriptive alt text so screen reader users understand their meaning and purpose.';
    } else if (id.includes('form') || id.includes('label') || id.includes('input') || id.includes('textarea') || id.includes('select') || before.includes('<input') || before.includes('<textarea') || before.includes('<select') || exp.includes('label')) {
        wcag = '1.3.1';
        severity = 'critical';
        title = 'Form input missing associated label';
        agent = 'FormAuditor';
        desc = 'Form controls must have associated labels (either via "for" attribute, wrapping, or ARIA attributes) to describe their purpose.';
    } else if (id.includes('contrast') || id.includes('color') || exp.includes('contrast') || exp.includes('color')) {
        wcag = '1.4.3';
        severity = 'warning';
        title = 'Insufficient text color contrast ratio';
        agent = 'DocAuditor';
        desc = 'The contrast ratio between text and its background must be at least 4.5:1 (or 3:1 for large text) to be readable.';
    } else if (id.includes('link') || id.includes('button') || before.includes('<a ') || before.includes('<button') || exp.includes('link') || exp.includes('button')) {
        wcag = '2.4.4';
        severity = 'critical';
        title = 'Empty interactive element (link/button)';
        agent = 'DocAuditor';
        desc = 'Interactive elements like links and buttons must have accessible names (visible text or ARIA labels) so assistive technologies can announce them.';
    } else if (id.includes('lang') || id.includes('html') || before.includes('<html') || exp.includes('lang attribute') || exp.includes('language')) {
        wcag = '3.1.1';
        severity = 'critical';
        title = 'Document language attribute missing';
        agent = 'DocAuditor';
        desc = 'The root HTML element must have a valid lang attribute conforming to BCP 47 (e.g. "es", "en") so screen readers parse correct voice outputs.';
    } else if (id.includes('trap') || id.includes('focus') || id.includes('tabindex') || exp.includes('focus') || exp.includes('keyboard')) {
        wcag = '2.1.2';
        severity = 'critical';
        title = 'Keyboard accessibility issue / focus trap';
        agent = 'KeyboardAuditor';
        desc = 'Keyboard focus must not be trapped in interactive elements, and tab order must be logical and intuitive.';
    }

    return { wcag, severity, title, agent, desc };
}

function escapeHtml(unsafe) {
    if (!unsafe) return "";
    return unsafe
         .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;")
         .replace(/"/g, "&quot;")
         .replace(/'/g, "&#039;");
}

function escapeDoubleBackticks(str) {
    if (!str) return "";
    return str
        .replace(/\\/g, '\\\\')
        .replace(/`/g, '\\`')
        .replace(/\$/g, '\\$');
}

// Expose functions globally to be called from dynamically injected markup
window.toggleFinding = toggleFinding;
window.copyText = copyText;
window.applyFix = applyFix;
window.resetToConfigure = resetToConfigure;


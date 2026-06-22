function toggleCustom() {
    const select = document.getElementById('source');
    const customInput = document.getElementById('custom_source');
    if (select.value === 'custom') {
        customInput.style.display = 'block';
    } else {
        customInput.style.display = 'none';
        customInput.value = '';
    }
}

async function runAudit() {
    let source = document.getElementById('source').value;
    if (source === 'custom') {
        source = document.getElementById('custom_source').value;
    }
    
    const rawHtml = document.getElementById('raw_html').value;
    
    document.getElementById('loader').style.display = 'block';
    document.getElementById('results').style.display = 'none';
    
    try {
        const response = await fetch('/api/audit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source: source, raw_html: rawHtml || null })
        });
        
        const data = await response.json();
        const resultsContent = document.getElementById('results-content');
        resultsContent.innerHTML = '';
        
        if (data.status === 'success') {
            const fixes = data.data;
            if (fixes.length === 0) {
                resultsContent.innerHTML = '<p>No accessibility issues found! 🎉</p>';
            } else {
                fixes.forEach(fix => {
                    const fixElement = document.createElement('div');
                    fixElement.className = 'fix-card';
                    fixElement.innerHTML = `
                        <h3>Finding ID: ${fix.finding_id || "N/A"}</h3>
                        <p><strong>Explanation:</strong> ${fix.explanation || "N/A"}</p>
                        <h4>Before:</h4>
                        <div class="code-block code-before">${escapeHtml(fix.before || "N/A")}</div>
                        <h4>After:</h4>
                        <div class="code-block">${escapeHtml(fix.after || "N/A")}</div>
                    `;
                    resultsContent.appendChild(fixElement);
                });
            }
        } else {
            resultsContent.innerHTML = `<p style="color: #fca5a5;">Error: ${data.message}</p>`;
        }
        
        document.getElementById('results').style.display = 'block';
    } catch (error) {
        alert('Failed to connect to the server.');
    } finally {
        document.getElementById('loader').style.display = 'none';
    }
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

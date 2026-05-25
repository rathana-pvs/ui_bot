let socket = null;
let isBotActive = false;

document.addEventListener("DOMContentLoaded", () => {
    initWebSocket();
    setupEventListeners();
    
    // Register Service Worker for PWA installability
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js')
            .then(() => console.log('Service Worker Registered'))
            .catch(err => console.error('Service Worker registration failed:', err));
    }
});

// Initialize WebSocket Connection (auto-handles HTTP/HTTPS to WS/WSS for tunneling)
function initWebSocket() {
    const loc = window.location;
    let wsUri = "";
    if (loc.protocol === "https:") {
        wsUri = "wss:";
    } else {
        wsUri = "ws:";
    }
    wsUri += "//" + loc.host + "/ws";

    console.log("Connecting to WebSocket: " + wsUri);
    socket = new WebSocket(wsUri);

    socket.onopen = () => {
        updateConnectionStatus(true);
    };

    socket.onclose = () => {
        updateConnectionStatus(false);
        // Try to reconnect every 3 seconds
        setTimeout(initWebSocket, 3000);
    };

    socket.onerror = (err) => {
        console.error("WebSocket error:", err);
    };

    socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        updateDashboard(data);
    };
}

function updateConnectionStatus(connected) {
    const dot = document.querySelector("#connection-status .status-dot");
    const text = document.querySelector("#connection-status .status-text");
    
    if (connected) {
        dot.className = "status-dot connected";
        text.innerText = "Connected";
    } else {
        dot.className = "status-dot disconnected";
        text.innerText = "Reconnecting...";
    }
}

// Event Listeners setup
function setupEventListeners() {
    const toggleBtn = document.getElementById("btn-toggle-bot");
    toggleBtn.addEventListener("click", () => {
        const nextState = !isBotActive;
        fetch("/api/toggle-bot", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ active: nextState })
        })
        .then(res => res.json())
        .then(data => {
            updatePowerBtn(data.active);
        })
        .catch(err => console.error("Error toggling bot state:", err));
    });
}

function updatePowerBtn(active) {
    isBotActive = active;
    const btn = document.getElementById("btn-toggle-bot");
    if (active) {
        btn.innerText = "ACTIVE";
        btn.className = "power-btn on";
    } else {
        btn.innerText = "INACTIVE";
        btn.className = "power-btn off";
    }
}

// Set Risk Profile API request
function setRiskProfile(profile) {
    fetch("/api/set-risk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile: profile })
    })
    .then(res => res.json())
    .then(data => {
        // UI is updated reactively via WebSocket callback
    })
    .catch(err => console.error("Error setting risk profile:", err));
}

// Close individual trade API request
function closeTrade(ticket) {
    if (!confirm(`Are you sure you want to close trade #${ticket}?`)) return;
    
    fetch(`/api/close-trade/${ticket}`, { method: "POST" })
    .catch(err => console.error("Error closing trade:", err));
}

// Close all active positions API request
function closeAllPositions() {
    if (!confirm("Are you sure you want to close ALL active positions?")) return;
    
    fetch("/api/close-all", { method: "POST" })
    .catch(err => console.error("Error closing all trades:", err));
}

// Main logic to update DOM with WebSocket packet data
function updateDashboard(data) {
    const { bot, account, positions } = data;

    // 1. Update power button & risk buttons
    updatePowerBtn(bot.is_active);
    updateRiskUI(bot.risk_profile);

    // 2. Update Account Stats
    const balance = account.balance || 0;
    const equity = account.equity || 0;
    const profit = account.profit || 0;
    const marginLevel = account.margin_level || 100;
    
    document.getElementById("val-balance").innerText = formatCurrency(balance);
    document.getElementById("val-equity").innerText = formatCurrency(equity);
    
    const profitEl = document.getElementById("val-profit");
    profitEl.innerText = formatCurrency(profit, true);
    if (profit > 0) {
        profitEl.className = "stat-value up";
    } else if (profit < 0) {
        profitEl.className = "stat-value down";
    } else {
        profitEl.className = "stat-value neutral";
    }
    
    document.getElementById("val-margin-level").innerText = `${marginLevel.toFixed(1)}%`;
    document.getElementById("val-server").innerText = `Server: ${account.server || 'Disconnected'}`;
    document.getElementById("val-login").innerText = account.login || '---';

    // 3. Update Regime Badges & Indicators
    updateAssetRegime("xauusd", bot.regimes["XAUUSD"], bot.metrics["XAUUSD"]);
    updateAssetRegime("xagusd", bot.regimes["XAGUSD"], bot.metrics["XAGUSD"]);

    // 4. Update Positions List (Table and Mobile Cards)
    renderPositions(positions);

    // 5. Update Log Console
    renderLogs(bot.logs);
}

function updateRiskUI(activeProfile) {
    const buttons = document.querySelectorAll(".risk-btn");
    buttons.forEach(btn => {
        if (btn.classList.contains(activeProfile)) {
            btn.classList.add("active");
        } else {
            btn.classList.remove("active");
        }
    });
}

function updateAssetRegime(symbolId, regime, metrics) {
    const badge = document.getElementById(`badge-${symbolId}`);
    const atrVal = document.getElementById(`metric-${symbolId.substring(0,3)}-atr`);
    const atrSmaVal = document.getElementById(`metric-${symbolId.substring(0,3)}-atr-sma`);
    const subEl = document.getElementById(`sub-${symbolId}`);
    const card = document.getElementById(`card-${symbolId}`);

    // Update Badge text and class
    badge.innerText = regime || "UNKNOWN";
    if (regime === "RANGING") {
        badge.className = "regime-badge ranging";
        card.style.boxShadow = "none";
    } else if (regime === "TRENDING") {
        badge.className = "regime-badge trending";
        // Light neon highlight for trending
        card.style.boxShadow = "0 8px 32px 0 rgba(0, 114, 255, 0.08)";
    } else {
        badge.className = "regime-badge unknown";
    }

    if (metrics && Object.keys(metrics).length > 0) {
        atrVal.innerText = metrics.atr_m15 ? metrics.atr_m15.toFixed(3) : "0.00";
        atrSmaVal.innerText = metrics.atr_sma_m15 ? metrics.atr_sma_m15.toFixed(3) : "0.00";

        // Display regime specific indicators
        if (regime === "RANGING") {
            subEl.innerHTML = `
                RSI (14): <strong style="color:#fff">${metrics.rsi ? metrics.rsi.toFixed(1) : '---'}</strong><br>
                BB Upper: <strong style="color:var(--text-secondary)">${metrics.upper_band ? metrics.upper_band.toFixed(2) : '---'}</strong><br>
                BB Lower: <strong style="color:var(--text-secondary)">${metrics.lower_band ? metrics.lower_band.toFixed(2) : '---'}</strong><br>
                BB Middle: <strong style="color:var(--text-secondary)">${metrics.middle_band ? metrics.middle_band.toFixed(2) : '---'}</strong>
            `;
        } else {
            subEl.innerHTML = `
                EMA (9): <strong style="color:var(--accent-blue)">${metrics.ema9 ? metrics.ema9.toFixed(2) : '---'}</strong><br>
                EMA (21): <strong style="color:var(--accent-amber)">${metrics.ema21 ? metrics.ema21.toFixed(2) : '---'}</strong><br>
                ATR (M5): <strong style="color:#fff">${metrics.atr ? metrics.atr.toFixed(2) : '---'}</strong>
            `;
        }
    } else {
        atrVal.innerText = "0.00";
        atrSmaVal.innerText = "0.00";
        subEl.innerText = "Waiting for data ticks...";
    }
}

function renderPositions(positions) {
    const tbody = document.getElementById("positions-body");
    const mList = document.getElementById("mobile-positions-list");
    
    tbody.innerHTML = "";
    mList.innerHTML = "";

    if (!positions || positions.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: rgba(255,255,255,0.4);">No active positions.</td></tr>`;
        mList.innerHTML = `<div style="text-align: center; color: rgba(255,255,255,0.4); padding: 20px;">No active positions.</div>`;
        return;
    }

    positions.forEach(pos => {
        const typeBadge = pos.type === "BUY" ? '<span class="badge-buy">BUY</span>' : '<span class="badge-sell">SELL</span>';
        const profitClass = pos.profit > 0 ? "up" : (pos.profit < 0 ? "down" : "");
        const formattedProfit = formatCurrency(pos.profit, true);

        // 1. Table Row (Desktop)
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>#${pos.ticket}</td>
            <td><strong>${pos.symbol}</strong></td>
            <td>${typeBadge}</td>
            <td>${pos.volume.toFixed(2)}</td>
            <td>${pos.price_open.toFixed(2)}</td>
            <td>${pos.price_current.toFixed(2)}</td>
            <td class="${profitClass}"><strong>${formattedProfit}</strong></td>
            <td><button class="close-btn" onclick="closeTrade(${pos.ticket})">Close</button></td>
        `;
        tbody.appendChild(tr);

        // 2. Card Row (Mobile)
        const card = document.createElement("div");
        card.className = "mobile-pos-card";
        card.innerHTML = `
            <div class="mobile-pos-header">
                <strong>${pos.symbol} ${typeBadge} (${pos.volume.toFixed(2)} Lots)</strong>
                <button class="close-btn" onclick="closeTrade(${pos.ticket})">Close</button>
            </div>
            <div class="mobile-pos-detail-row">
                <span>Ticket:</span>
                <span>#${pos.ticket}</span>
            </div>
            <div class="mobile-pos-detail-row">
                <span>Entry Price:</span>
                <span>${pos.price_open.toFixed(2)}</span>
            </div>
            <div class="mobile-pos-detail-row">
                <span>Current Price:</span>
                <span>${pos.price_current.toFixed(2)}</span>
            </div>
            <div class="mobile-pos-detail-row">
                <span>Profit / Loss:</span>
                <span class="${profitClass}">${formattedProfit}</span>
            </div>
        `;
        mList.appendChild(card);
    });
}

function renderLogs(logs) {
    const consoleBox = document.getElementById("console-box");
    // Only repaint if logs length changes or is updated
    consoleBox.innerHTML = "";
    
    if (!logs || logs.length === 0) {
        consoleBox.innerHTML = '<div class="log-line text-muted">Console initialized...</div>';
        return;
    }
    
    logs.forEach(line => {
        const div = document.createElement("div");
        div.className = "log-line";
        div.innerText = line;
        consoleBox.appendChild(div);
    });
    
    // Auto-scroll to bottom of console
    consoleBox.scrollTop = consoleBox.scrollHeight;
}

// Helpers
function formatCurrency(value, showPlus = false) {
    const absVal = Math.abs(value).toFixed(2);
    let str = `$${absVal}`;
    if (value < 0) {
        str = `-$${absVal}`;
    } else if (value > 0 && showPlus) {
        str = `+$${absVal}`;
    }
    return str;
}

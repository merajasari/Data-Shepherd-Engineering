/*
Stock Market AI Platform
Live dashboard + 26-stock future trend forecast
*/

const LIVE_REFRESH_MS = 10000;

let liveRefreshTimer = null;
let lastMainPrice = null;


/*
--------------------------------------------------
Basic helpers
--------------------------------------------------
*/

function money(value) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "N/A";
    }

    return `$${number.toFixed(2)}`;
}


function percent(value, digits = 1) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "N/A";
    }

    return `${(number * 100).toFixed(digits)}%`;
}


function getSelectedSymbol() {
    const params =
        new URLSearchParams(
            window.location.search
        );

    const querySymbol =
        params.get("symbol");

    if (querySymbol) {
        return querySymbol
            .trim()
            .toUpperCase();
    }

    const symbolElement =
        document.querySelector(
            ".symbol"
        );

    if (
        symbolElement
        && symbolElement.textContent
    ) {
        return symbolElement
            .textContent
            .trim()
            .toUpperCase();
    }

    return "AAPL";
}


/*
--------------------------------------------------
Main selected-stock live price
--------------------------------------------------
*/

function getMainPriceElement() {
    return document.querySelector(
        ".price-block .price"
    );
}


function getMainPriceBlock() {
    return document.querySelector(
        ".price-block"
    );
}


function getOrCreateMainStatus() {
    const priceBlock =
        getMainPriceBlock();

    if (!priceBlock) {
        return null;
    }

    let label =
        document.getElementById(
            "live-price-source"
        );

    if (label) {
        return label;
    }

    label =
        document.createElement(
            "div"
        );

    label.id =
        "live-price-source";

    label.style.marginTop =
        "6px";

    label.style.fontSize =
        ".72rem";

    label.style.fontWeight =
        "900";

    label.style.letterSpacing =
        ".08em";

    priceBlock.appendChild(
        label
    );

    return label;
}


function showMainEod() {
    const label =
        getOrCreateMainStatus();

    if (!label) {
        return;
    }

    label.textContent =
        "LATEST EOD";

    label.style.color =
        "#91a6c2";
}


function showMainLive(quote) {
    const label =
        getOrCreateMainStatus();

    if (!label) {
        return;
    }

    label.textContent =
        "● LIVE IEX";

    label.style.color =
        "#39e3a1";

    if (quote.received_at) {
        const date =
            new Date(
                quote.received_at
            );

        if (
            !Number.isNaN(
                date.getTime()
            )
        ) {
            label.title =
                `Last update: ${date.toLocaleString()}`;
        }
    }
}


function showMainChecking() {
    const label =
        getOrCreateMainStatus();

    if (!label) {
        return;
    }

    label.textContent =
        "LIVE FEED CHECKING";

    label.style.color =
        "#efc56b";
}


function updateMainPrice(quote) {
    const element =
        getMainPriceElement();

    if (!element) {
        return;
    }

    const price =
        Number(
            quote.reference_price
        );

    if (!Number.isFinite(price)) {
        return;
    }

    if (
        lastMainPrice !== null
        && price !== lastMainPrice
    ) {
        element.style.transition =
            "transform .15s ease";

        element.style.transform =
            "scale(1.025)";

        window.setTimeout(
            () => {
                element.style.transform =
                    "scale(1)";
            },
            160
        );
    }

    element.textContent =
        money(price);

    lastMainPrice =
        price;
}


async function fetchSelectedLiveQuote() {
    const symbol =
        getSelectedSymbol();

    const response =
        await fetch(
            `/api/live/${encodeURIComponent(symbol)}?t=${Date.now()}`,
            {
                cache: "no-store"
            }
        );

    if (!response.ok) {
        throw new Error(
            `Live quote API returned ${response.status}`
        );
    }

    return response.json();
}


async function refreshSelectedStock() {
    try {
        const quote =
            await fetchSelectedLiveQuote();

        if (
            quote
            && quote.available
            && quote.reference_price !== null
            && quote.reference_price !== undefined
        ) {
            updateMainPrice(
                quote
            );

            showMainLive(
                quote
            );

            return;
        }

        showMainEod();

    } catch (error) {
        console.warn(
            "Selected live price refresh failed:",
            error
        );

        showMainChecking();
    }
}


/*
--------------------------------------------------
Top 10 live prices
--------------------------------------------------
*/

function updateTop10Cell(
    cell,
    stock
) {
    const livePrice =
        Number(
            stock.live_price
        );

    const displayPrice =
        Number(
            stock.display_price
        );

    if (
        stock.live_available
        && Number.isFinite(
            livePrice
        )
    ) {
        cell.textContent =
            money(
                livePrice
            );

        cell.title =
            "LIVE IEX";

        cell.style.color =
            "#39e3a1";

        return;
    }

    if (
        Number.isFinite(
            displayPrice
        )
    ) {
        cell.textContent =
            money(
                displayPrice
            );
    }

    cell.title =
        "LATEST EOD";

    cell.style.color =
        "";
}


async function refreshTop10Prices() {
    try {
        const response =
            await fetch(
                `/api/stocks?t=${Date.now()}`,
                {
                    cache: "no-store"
                }
            );

        if (!response.ok) {
            throw new Error(
                `Stock API returned ${response.status}`
            );
        }

        const stocks =
            await response.json();

        for (
            const stock of stocks
        ) {
            const selector =
                `[data-live-price-symbol="${stock.symbol}"]`;

            const cell =
                document.querySelector(
                    selector
                );

            if (!cell) {
                continue;
            }

            updateTop10Cell(
                cell,
                stock
            );
        }

    } catch (error) {
        console.warn(
            "Top 10 live price refresh failed:",
            error
        );
    }
}


/*
--------------------------------------------------
26-stock future trend forecast
--------------------------------------------------
*/

function forecastColor(score) {
    if (score >= 20) {
        return "#39e3a1";
    }

    if (score <= -20) {
        return "#ff6680";
    }

    return "#efc56b";
}


function forecastDirectionLabel(score) {
    if (score >= 50) {
        return "STRONG BULLISH";
    }

    if (score >= 20) {
        return "BULLISH";
    }

    if (score > -20) {
        return "NEUTRAL";
    }

    if (score > -50) {
        return "BEARISH";
    }

    return "STRONG BEARISH";
}


function renderForecastSummary(
    forecasts
) {
    const container =
        document.getElementById(
            "forecast-summary"
        );

    if (!container) {
        return;
    }

    const valid =
        forecasts.filter(
            item =>
                Number.isFinite(
                    Number(
                        item.forecast_score
                    )
                )
        );

    const bullish =
        valid.filter(
            item =>
                Number(
                    item.forecast_score
                ) > 20
        ).length;

    const neutral =
        valid.filter(
            item => {
                const score =
                    Number(
                        item.forecast_score
                    );

                return (
                    score >= -20
                    && score <= 20
                );
            }
        ).length;

    const bearish =
        valid.filter(
            item =>
                Number(
                    item.forecast_score
                ) < -20
        ).length;

    container.innerHTML = `
        <div
            style="
                background:var(--panel2);
                border:1px solid var(--border);
                border-radius:12px;
                padding:14px;
            "
        >
            <div
                style="
                    color:var(--muted);
                    font-size:.72rem;
                    font-weight:900;
                    letter-spacing:.08em;
                "
            >
                BULLISH
            </div>

            <strong
                style="
                    display:block;
                    margin-top:4px;
                    color:#39e3a1;
                    font-size:1.4rem;
                "
            >
                ${bullish}
            </strong>
        </div>

        <div
            style="
                background:var(--panel2);
                border:1px solid var(--border);
                border-radius:12px;
                padding:14px;
            "
        >
            <div
                style="
                    color:var(--muted);
                    font-size:.72rem;
                    font-weight:900;
                    letter-spacing:.08em;
                "
            >
                NEUTRAL
            </div>

            <strong
                style="
                    display:block;
                    margin-top:4px;
                    color:#efc56b;
                    font-size:1.4rem;
                "
            >
                ${neutral}
            </strong>
        </div>

        <div
            style="
                background:var(--panel2);
                border:1px solid var(--border);
                border-radius:12px;
                padding:14px;
            "
        >
            <div
                style="
                    color:var(--muted);
                    font-size:.72rem;
                    font-weight:900;
                    letter-spacing:.08em;
                "
            >
                BEARISH
            </div>

            <strong
                style="
                    display:block;
                    margin-top:4px;
                    color:#ff6680;
                    font-size:1.4rem;
                "
            >
                ${bearish}
            </strong>
        </div>

        <div
            style="
                background:var(--panel2);
                border:1px solid var(--border);
                border-radius:12px;
                padding:14px;
            "
        >
            <div
                style="
                    color:var(--muted);
                    font-size:.72rem;
                    font-weight:900;
                    letter-spacing:.08em;
                "
            >
                TOTAL MODELS
            </div>

            <strong
                style="
                    display:block;
                    margin-top:4px;
                    font-size:1.4rem;
                "
            >
                ${valid.length}
            </strong>
        </div>
    `;
}


function renderForecastChart(
    forecasts
) {
    const container =
        document.getElementById(
            "forecast-chart"
        );

    if (!container) {
        return;
    }

    const valid =
        forecasts
            .filter(
                item =>
                    Number.isFinite(
                        Number(
                            item.forecast_score
                        )
                    )
            )
            .sort(
                (a, b) =>
                    Number(
                        b.forecast_score
                    )
                    -
                    Number(
                        a.forecast_score
                    )
            );

    if (!valid.length) {
        container.innerHTML =
            `
            <div style="color:var(--muted);">
                Forecast data unavailable.
            </div>
            `;

        return;
    }

    container.innerHTML = "";

    for (
        const forecast of valid
    ) {
        const score =
            Number(
                forecast.forecast_score
            );

        const probabilityUp =
            Number(
                forecast.probability_up
            );

        const accuracy =
            Number(
                forecast.accuracy
            );

        const baseline =
            Number(
                forecast.majority_baseline
            );

        const width =
            Math.min(
                Math.abs(score),
                100
            ) / 2;

        const color =
            forecastColor(
                score
            );

        const row =
            document.createElement(
                "div"
            );

        row.style.display =
            "grid";

        row.style.gridTemplateColumns =
            "70px minmax(220px,1fr) 92px";

        row.style.gap =
            "12px";

        row.style.alignItems =
            "center";

        row.style.padding =
            "6px 0";

        const direction =
            forecastDirectionLabel(
                score
            );

        row.innerHTML = `
            <strong
                style="
                    font-size:.9rem;
                "
            >
                ${forecast.symbol}
            </strong>

            <div>
                <div
                    style="
                        position:relative;
                        height:22px;
                        background:rgba(255,255,255,.045);
                        border:1px solid var(--border);
                        border-radius:7px;
                        overflow:hidden;
                    "
                >

                    <div
                        style="
                            position:absolute;
                            left:50%;
                            top:0;
                            bottom:0;
                            width:1px;
                            background:rgba(255,255,255,.32);
                            z-index:3;
                        "
                    ></div>

                    <div
                        style="
                            position:absolute;
                            top:3px;
                            bottom:3px;
                            ${score >= 0
                                ? "left:50%;"
                                : "right:50%;"}
                            width:${width}%;
                            background:${color};
                            border-radius:5px;
                            opacity:.92;
                        "
                    ></div>

                </div>

                <div
                    style="
                        display:flex;
                        justify-content:space-between;
                        gap:10px;
                        margin-top:4px;
                        color:var(--muted);
                        font-size:.68rem;
                    "
                >
                    <span>
                        ${direction}
                    </span>

                    <span>
                        UP ${Number.isFinite(probabilityUp)
                            ? percent(probabilityUp)
                            : "N/A"}
                        · ACC ${Number.isFinite(accuracy)
                            ? percent(accuracy)
                            : "N/A"}
                        · BASE ${Number.isFinite(baseline)
                            ? percent(baseline)
                            : "N/A"}
                    </span>
                </div>
            </div>

            <strong
                style="
                    color:${color};
                    text-align:right;
                    font-size:.9rem;
                "
            >
                ${score >= 0 ? "+" : ""}${score.toFixed(1)}
            </strong>
        `;

        container.appendChild(
            row
        );
    }
}


async function refreshForecast() {
    try {
        const response =
            await fetch(
                `/api/forecast?t=${Date.now()}`,
                {
                    cache: "no-store"
                }
            );

        if (!response.ok) {
            throw new Error(
                `Forecast API returned ${response.status}`
            );
        }

        const data =
            await response.json();

        const forecasts =
            Array.isArray(
                data.forecasts
            )
                ? data.forecasts
                : [];

        renderForecastSummary(
            forecasts
        );

        renderForecastChart(
            forecasts
        );

    } catch (error) {
        console.warn(
            "Forecast refresh failed:",
            error
        );

        const container =
            document.getElementById(
                "forecast-chart"
            );

        if (container) {
            container.innerHTML =
                `
                <div
                    style="
                        color:#efc56b;
                    "
                >
                    Forecast data temporarily unavailable.
                </div>
                `;
        }
    }
}


/*
--------------------------------------------------
Combined refresh scheduler
--------------------------------------------------
*/

async function refreshDashboard() {
    await Promise.allSettled([
        refreshSelectedStock(),
        refreshTop10Prices(),
        refreshForecast()
    ]);
}


function startLiveRefresh() {
    if (liveRefreshTimer) {
        window.clearInterval(
            liveRefreshTimer
        );
    }

    refreshDashboard();

    liveRefreshTimer =
        window.setInterval(
            refreshDashboard,
            LIVE_REFRESH_MS
        );
}


function stopLiveRefresh() {
    if (!liveRefreshTimer) {
        return;
    }

    window.clearInterval(
        liveRefreshTimer
    );

    liveRefreshTimer =
        null;
}


document.addEventListener(
    "visibilitychange",
    () => {
        if (
            document.visibilityState
            === "visible"
        ) {
            startLiveRefresh();
        } else {
            stopLiveRefresh();
        }
    }
);


document.addEventListener(
    "DOMContentLoaded",
    () => {
        showMainEod();
        startLiveRefresh();
    }
);

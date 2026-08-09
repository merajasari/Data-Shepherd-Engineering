/*
Stock Market AI Platform
Live dashboard client
*/

const LIVE_REFRESH_MS = 10000;

let liveRefreshTimer = null;
let lastMainPrice = null;


function money(value) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "N/A";
    }

    return `$${number.toFixed(2)}`;
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


function showMainLive(
    quote
) {
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
                `Last update: ${
                    date.toLocaleString()
                }`;
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


function updateMainPrice(
    quote
) {
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
            `Live quote API returned ${
                response.status
            }`
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
                `Stock API returned ${
                    response.status
                }`
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


async function refreshDashboard() {
    await Promise.allSettled([
        refreshSelectedStock(),
        refreshTop10Prices()
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

let priceChart = null;


const TOP_SYMBOLS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
    "AVGO",
    "AMD",
    "ORCL"
];


function percent(value, digits = 1) {
    return `${(Number(value) * 100).toFixed(digits)}%`;
}


function signedPercent(value, digits = 1) {
    const number = Number(value) * 100;

    return `${number >= 0 ? "+" : ""}${number.toFixed(digits)}%`;
}


function money(value) {
    return `$${Number(value).toFixed(2)}`;
}


function safeNumber(value, digits = 1) {
    if (
        value === null
        || value === undefined
        || Number.isNaN(Number(value))
    ) {
        return "N/A";
    }

    return Number(value).toFixed(digits);
}


function directionClass(direction) {
    return (
        direction === "UP"
            ? "prediction-up"
            : "prediction-down"
    );
}


function edgeClass(edge) {
    if (edge > 0) {
        return "positive";
    }

    if (edge < 0) {
        return "negative";
    }

    return "";
}


async function loadStocks() {

    const response = await fetch(
        "/api/stocks"
    );

    if (!response.ok) {
        throw new Error(
            `Stock API failed: ${response.status}`
        );
    }

    const stocks = await response.json();

    renderRanking(stocks);
    renderStockCards(stocks);
}


function renderRanking(stocks) {

    const tbody =
        document.getElementById(
            "ranking-body"
        );

    tbody.innerHTML = "";


    for (const stock of stocks) {

        const edge =
            Number(stock.accuracy)
            - Number(
                stock.majority_baseline
            );


        const row =
            document.createElement(
                "tr"
            );


        row.innerHTML = `
            <td>
                <strong>
                    ${stock.symbol}
                </strong>
            </td>

            <td
                class="${directionClass(
                    stock.prediction
                )}"
            >
                ${stock.prediction}
            </td>

            <td>
                ${percent(
                    stock.output_probability
                )}
            </td>

            <td>
                ${percent(
                    stock.accuracy
                )}
            </td>

            <td>
                ${percent(
                    stock.majority_baseline
                )}
            </td>

            <td
                class="${edgeClass(edge)}"
            >
                ${signedPercent(edge)}
            </td>
        `;


        tbody.appendChild(
            row
        );
    }
}


function renderStockCards(stocks) {

    const grid =
        document.getElementById(
            "stock-grid"
        );

    grid.innerHTML = "";


    for (const stock of stocks) {

        const edge =
            Number(stock.accuracy)
            - Number(
                stock.majority_baseline
            );


        const card =
            document.createElement(
                "article"
            );

        card.className =
            "stock-card";


        card.innerHTML = `
            <div class="stock-card-header">

                <div>
                    <div class="stock-symbol">
                        ${stock.symbol}
                    </div>

                    <div class="stock-date">
                        ${String(
                            stock.timestamp
                        ).slice(0, 10)}
                    </div>
                </div>

                <div class="stock-price-block">

                    <div class="stock-price">
                        ${money(
                            stock.close
                        )}
                    </div>

                    <div
                        class="
                        stock-change
                        ${
                            Number(
                                stock.price_change_pct
                            ) >= 0
                                ? "positive"
                                : "negative"
                        }
                        "
                    >
                        ${signedPercent(
                            stock.price_change_pct
                        )}
                    </div>

                </div>

            </div>


            <div class="prediction-section">

                <div>

                    <div class="mini-label">
                        5-DAY AI DIRECTION
                    </div>

                    <div
                        class="
                        mini-direction
                        ${directionClass(
                            stock.prediction
                        )}
                        "
                    >
                        ${stock.prediction}
                    </div>

                </div>


                <div class="mini-probability">

                    <strong>
                        ${percent(
                            stock.output_probability
                        )}
                    </strong>

                    <span>
                        MODEL OUTPUT
                    </span>

                </div>

            </div>


            <div class="probability-bar-wrap">

                <div class="probability-label-row">

                    <span>
                        UP
                    </span>

                    <span>
                        ${percent(
                            stock.probability_up
                        )}
                    </span>

                </div>


                <div class="mini-bar">

                    <div
                        class="mini-bar-fill up-bar"
                        style="
                            width:
                            ${
                                Number(
                                    stock.probability_up
                                ) * 100
                            }%;
                        "
                    ></div>

                </div>

            </div>


            <div class="metric-grid-small">

                <div>
                    <span>RSI</span>

                    <strong>
                        ${safeNumber(
                            stock.rsi_14,
                            1
                        )}
                    </strong>
                </div>


                <div>
                    <span>SMA 20</span>

                    <strong>
                        ${money(
                            stock.sma_20
                        )}
                    </strong>
                </div>


                <div>
                    <span>VOL 20D</span>

                    <strong>
                        ${percent(
                            stock.volatility_20d,
                            2
                        )}
                    </strong>
                </div>


                <div>
                    <span>VOLUME RATIO</span>

                    <strong>
                        ${safeNumber(
                            stock.volume_ratio,
                            2
                        )}x
                    </strong>
                </div>

            </div>


            <div class="model-quality">

                <div>
                    <span>
                        MODEL ACCURACY
                    </span>

                    <strong>
                        ${percent(
                            stock.accuracy
                        )}
                    </strong>
                </div>


                <div>
                    <span>
                        BASELINE
                    </span>

                    <strong>
                        ${percent(
                            stock.majority_baseline
                        )}
                    </strong>
                </div>

            </div>


            <div class="model-edge">

                <span
                    class="${
                        edge > 0
                            ? "edge-positive"
                            : edge < 0
                                ? "edge-negative"
                                : "edge-neutral"
                    }"
                >

                    ${
                        edge > 0
                            ? "MODEL EDGE"
                            : edge < 0
                                ? "BELOW BASELINE"
                                : "MATCHES BASELINE"
                    }

                    ${signedPercent(edge)}

                </span>

            </div>
        `;


        grid.appendChild(
            card
        );
    }
}


async function loadPriceChart(symbol) {

    const response =
        await fetch(
            `/api/prices/${symbol}`
        );


    if (!response.ok) {

        throw new Error(
            `Price API failed for ${symbol}: ${response.status}`
        );
    }


    const rows =
        await response.json();


    if (!rows.length) {
        return;
    }


    const labels =
        rows.map(
            row =>
                String(
                    row.timestamp
                ).slice(0, 10)
        );


    const close =
        rows.map(
            row =>
                Number(
                    row.close
                )
        );


    const sma20 =
        rollingAverage(
            close,
            20
        );


    const sma50 =
        rollingAverage(
            close,
            50
        );


    const sma200 =
        rollingAverage(
            close,
            200
        );


    const title =
        document.getElementById(
            "chart-title"
        );


    title.textContent =
        `${symbol} Price History`;


    const canvas =
        document.getElementById(
            "priceChart"
        );


    const context =
        canvas.getContext(
            "2d"
        );


    if (priceChart) {
        priceChart.destroy();
    }


    priceChart =
        new Chart(
            context,
            {
                type: "line",

                data: {
                    labels,

                    datasets: [
                        {
                            label: "Close",
                            data: close,
                            borderWidth: 3,
                            pointRadius: 0,
                            tension: 0.18
                        },

                        {
                            label: "SMA 20",
                            data: sma20,
                            borderWidth: 2,
                            pointRadius: 0,
                            tension: 0.15
                        },

                        {
                            label: "SMA 50",
                            data: sma50,
                            borderWidth: 2,
                            pointRadius: 0,
                            tension: 0.15
                        },

                        {
                            label: "SMA 200",
                            data: sma200,
                            borderWidth: 2,
                            pointRadius: 0,
                            tension: 0.15
                        }
                    ]
                },


                options: {

                    responsive: true,

                    maintainAspectRatio: false,


                    interaction: {
                        mode: "index",
                        intersect: false
                    },


                    plugins: {

                        legend: {

                            labels: {
                                color:
                                    "#a8bad0"
                            }
                        },


                        tooltip: {

                            callbacks: {

                                label: function(
                                    context
                                ) {

                                    const value =
                                        context.parsed.y;

                                    if

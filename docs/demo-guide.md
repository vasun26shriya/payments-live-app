# Demonstrating Payments Lab

Prepared as an AI-assisted contribution for the connected Shreya (`yasho-26singh`) account. This draft does not claim that Shreya authored the project's earlier implementation.

Open https://payments-live-app.vercel.app in a browser. The dashboard should report **API connected** and **MongoDB · persistent storage**. This is a simulation: no card information or bank connection is needed.

## A five-minute demonstration

1. Enter `42.00`, keep `INR`, select **Successful**, and click **Create order**. Confirm that the result says **Paid** and includes an order ID and transaction ID. The API amount is `4200`, representing paise.
2. Click **Retrieve saved order**. Confirm that the same order and transaction IDs return. Refresh the page and find the order in **Your orders**; click its **View** button to fetch the saved result again.
3. Enter `15.00`, select **Declined**, and create another order. Confirm **Failed** with an amount of ₹15.00. A failure is a saved outcome, rather than a missing record.
4. Scroll to **One key. One transaction.** and click **Run the retry experiment**. Confirm three `200 OK` results with identical transaction IDs, followed by **Changed amount · 409 Conflict**.
5. Open the API reference at https://payments-live-app.vercel.app/api/docs to show the server's documented endpoints.

## Explain what the experiment proves

Payment retries use one idempotency key and identical payload. The database stores the first result atomically and returns it for duplicates. A different payload cannot reuse that key. Creating an order again creates another order; order creation is not protected by a client idempotency key.

The hosted edition uses one FastAPI backend with MongoDB Atlas. The original repository separately demonstrates Orders and Payments services, Docker, Kubernetes, Helm, and monitoring. Do not describe that local stack as running inside the Vercel deployment.

## Common surprises

| Observation | Explanation or next step |
|---|---|
| The history is empty in another browser | Records are scoped to a browser session; this is not an account login system. |
| The latest result disappears after reload | Select the saved row's **View** button. History remains available in the same session. |
| More clicks create more orders | Each order submission creates a new order. Use the retry experiment to demonstrate payment deduplication. |
| Requests return 429 | The session exceeded 30 writes in a minute. Wait until the next minute before continuing. |
| The backend reports unavailable | Check `/api/health`. Database configuration or connectivity may need attention; a visible frontend alone does not prove a working backend. |
| Old records disappear | Demo records have seven-day retention; MongoDB TTL cleanup is asynchronous. |

## Video and interview presentation

The repository includes a 3:55 narrated video at `docs/demo/Payments-Lab-Explained-and-Live-Demo.mp4`, with a transcript and captions in the same folder. The video shows actual public-app captures; pauses are shortened and narration is synthetic.

A concise explanation: “This order and payment simulation stores results reliably and prevents duplicate payment transactions. I can demonstrate successful and declined payments, persistent retrieval, and concurrent retries that all return one transaction.”

# ScanLink Developer Guide

This guide is for web application developers who want to trigger scans from a browser-based system and receive the scanned PDF back from the local Windows workstation.

ScanLink runs on the user's Windows machine as a tray application. Your web app talks to it through a loopback HTTP/HTTPS API or opens the registered `scanlink://` protocol.

## Integration Model

ScanLink is designed for apps that are hosted somewhere else but need access to scanner hardware attached to the user's PC.

Typical flow:

1. User opens your web application in a browser.
2. Your frontend checks whether ScanLink is running with `GET /health`.
3. User clicks a scan button.
4. Your frontend posts to `POST /scan`.
5. Your frontend polls `GET /scan/<job_id>` until completion.
6. Your frontend downloads the PDF from `GET /scan/<job_id>/result`.
7. Your app uploads or attaches the PDF to the target document record.

The local API listens on:

- `http://127.0.0.1:5000`
- `https://127.0.0.1:5443` when trusted localhost certificates are available

The bundled `static/scanlink.js` helper tries HTTPS first and falls back to HTTP.

## Browser Example

Include the helper in your page:

```html
<script src="/static/scanlink.js"></script>
```

Use it from your scan button:

```html
<button id="scan-button" type="button">Scan</button>

<script>
const scanLink = new ScanLink({
    onConnectionChange(connected) {
        console.log("ScanLink connected:", connected);
    },
    onStatus(status) {
        console.log("Scan status:", status.status, status.page_count || 0);
    },
    onPageScanned(pageCount) {
        console.log("Pages scanned:", pageCount);
    },
    onComplete(jobId, pageCount) {
        console.log("Scan complete:", jobId, pageCount);
    },
    onError(error) {
        console.error("ScanLink error:", error.code, error.message);
    },
});

document.getElementById("scan-button").addEventListener("click", async () => {
    const job = await scanLink.startScan({
        docId: "DOC-123",
        metadata: {
            source: "invoice-form",
        },
    });

    const pdfBlob = await scanLink.waitForResult(job.job_id);

    const formData = new FormData();
    formData.append("pdf", pdfBlob, `scan_${job.job_id}.pdf`);
    formData.append("job_id", job.job_id);

    await fetch("/documents/DOC-123/upload-scan/", {
        method: "POST",
        body: formData,
    });
});
</script>
```

## Raw Fetch Example

If you do not want to use the helper:

```js
async function scanDocument(docId) {
    const baseUrl = "http://127.0.0.1:5000";

    const startResponse = await fetch(`${baseUrl}/scan`, {
        method: "POST",
        mode: "cors",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doc_id: docId }),
    });

    if (!startResponse.ok) {
        throw await startResponse.json();
    }

    const { job_id } = await startResponse.json();

    while (true) {
        const statusResponse = await fetch(`${baseUrl}/scan/${job_id}`, {
            method: "GET",
            mode: "cors",
        });
        const job = await statusResponse.json();

        if (job.status === "completed") {
            const resultResponse = await fetch(`${baseUrl}/scan/${job_id}/result`, {
                method: "GET",
                mode: "cors",
            });
            return resultResponse.blob();
        }

        if (["failed", "cancelled", "timed_out"].includes(job.status)) {
            throw job.error || { code: job.status, message: "Scan failed." };
        }

        await new Promise((resolve) => setTimeout(resolve, 1000));
    }
}
```

## Deep Link Fallback

ScanLink registers a custom protocol during installation:

```html
<a href="scanlink://scan?docId=DOC-123">Scan</a>
```

Deep links are useful when the browser cannot call localhost directly or when you want a simple launch trigger. They do not return the PDF to the browser by themselves. For most web apps, use the REST API when you need a result file in the page.

Supported query parameters:

- `docId` or `doc_id`
- `callback` or `callback_url`

Example with callback:

```html
<a href="scanlink://scan?docId=DOC-123&callback=https%3A%2F%2Fexample.com%2Fscan-callback">
    Scan
</a>
```

If ScanLink is already running, a protocol launch forwards the command to the existing tray instance through the internal local endpoint.

## Callback URL

When `callback_url` is provided, ScanLink posts the completed PDF to that URL after a successful scan.

The callback request is `multipart/form-data` with:

- `pdf`: scanned PDF file
- `job_id`: ScanLink job ID
- `doc_id`: document ID from the original request, if provided
- `page_count`: number of scanned pages
- `status`: `completed`

Use callbacks when your backend can receive files directly and you do not want the browser to upload the PDF after polling.

## Status Lifecycle

Common statuses:

- `queued`: job accepted and waiting.
- `processing`: worker started the job.
- `selecting_scanner`: ScanLink is waiting for scanner selection.
- `acquiring`: scanner acquisition is active.
- `page_scanned`: at least one page has been captured. Check `page_count`.
- `generating_pdf`: pages are being converted to a PDF.
- `completed`: PDF is ready for download.
- `failed`: unrecoverable error.
- `cancelled`: user cancelled scanner selection or no pages were acquired.
- `timed_out`: scanner or helper process exceeded a timeout.

Only one scan job can be queued or running at a time. If another request arrives while busy, the API returns `409 busy`.

## Result Retention

Completed results are kept in memory temporarily. Defaults:

- Job metadata TTL: 900 seconds.
- Result PDF TTL: 300 seconds.

Downloading `/scan/<job_id>/result` consumes the stored PDF. A second download for the same job can return `410 result_unavailable`.

## Operational Notes

- The API is bound to `127.0.0.1`, not a public network interface.
- CORS defaults to `["*"]` in `%LOCALAPPDATA%\ScanLink\config.json`.
- The first scan may show a scanner selection dialog.
- If the user selects "Set as default scanner", later scans skip scanner selection.
- Tray settings control resolution, scanner UI visibility, paper protection, startup, and diagnostics.
- Silent scanning disables scanner UI by default and configures feeder/autofeed capabilities where supported.
- Paper protection is disabled by default because some TWAIN drivers report false paper-stuck errors during batch scanning.

## Useful Links

- [API Reference](api.md)
- [Architecture](architecture.md)
- [Building and Release](building.md)

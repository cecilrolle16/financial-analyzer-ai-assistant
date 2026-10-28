const form = document.querySelector("#review-form");
const fileInput = document.querySelector("#file");
const fileLabel = document.querySelector("#file-label");
const dropZone = document.querySelector("#drop-zone");
const submit = document.querySelector("#submit");
const status = document.querySelector("#status");
const results = document.querySelector("#results");

const MAX_BYTES = 4_500_000;
let selected = null;

fileInput.addEventListener("change", () => {
  setFile(fileInput.files[0]);
});

["dragover", "dragenter"].forEach((name) => {
  dropZone.addEventListener(name, (event) => {
    event.preventDefault();
    dropZone.classList.add("ready");
  });
});

dropZone.addEventListener("dragleave", () => dropZone.classList.remove("ready"));

dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropZone.classList.remove("ready");
  const file = event.dataTransfer.files[0];
  if (file) {
    fileInput.files = event.dataTransfer.files;
    setFile(file);
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selected) return;
  submit.disabled = true;
  results.hidden = true;
  results.innerHTML = "";
  setStatus("Uploading the PDF…");

  try {
    const ticket = await postJson("/upload-url", {
      filename: selected.name,
      contentType: "application/pdf",
      sizeBytes: selected.size,
    });
    const uploaded = await fetch(ticket.uploadUrl, {
      method: "PUT",
      headers: ticket.headers,
      body: selected,
    });
    if (!uploaded.ok) {
      throw new Error("The PDF could not be stored. Try again.");
    }
    setStatus("Reading the document…");
    const review = await postJson("/analyze", { key: ticket.key });
    render(review);
    setStatus("");
  } catch (error) {
    setStatus(error.message || "The review failed.", true);
  } finally {
    submit.disabled = !selected;
  }
});

function setFile(file) {
  selected = null;
  submit.disabled = true;
  if (!file) {
    fileLabel.textContent = "Choose a PDF or drop it here";
    return;
  }
  const looksLikePdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!looksLikePdf) {
    setStatus("Choose a PDF.", true);
    fileLabel.textContent = "Choose a PDF or drop it here";
    return;
  }
  if (file.size < 1 || file.size > MAX_BYTES) {
    setStatus("The PDF must be 4.5 MB or smaller.", true);
    fileLabel.textContent = "Choose a PDF or drop it here";
    return;
  }
  selected = file;
  submit.disabled = false;
  dropZone.classList.add("ready");
  fileLabel.textContent = `${file.name} · ${formatSize(file.size)}`;
  setStatus("");
}

async function postJson(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || "The analyzer could not complete that step.");
  }
  return data;
}

function render(review) {
  const figures = review.keyFigures.length
    ? `<ul class="figures">${review.keyFigures.map((item) =>
        `<li><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong></li>`
      ).join("")}</ul>`
    : "<p>No specific figures were called out.</p>";

  const problems = review.problems.length
    ? review.problems.map((item) => `
        <div class="problem">
          <div class="severity ${escapeHtml(item.severity)}">${escapeHtml(item.severity)}</div>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.detail)}</p>
        </div>`).join("")
    : "<p>No problems stood out in this document.</p>";

  const steps = review.recommendations.length
    ? `<ol class="recommendations">${review.recommendations.map((item) =>
        `<li>${escapeHtml(item)}</li>`
      ).join("")}</ol>`
    : "<p>No next step was suggested.</p>";

  results.innerHTML = `
    <article>
      <p class="kind">${escapeHtml(review.documentType)}</p>
      <h2>What this document says</h2>
      <p>${escapeHtml(review.summary)}</p>
    </article>
    <article>
      <h2>Key figures</h2>
      ${figures}
    </article>
    <article>
      <h2>Problems</h2>
      ${problems}
    </article>
    <article>
      <h2>What to do next</h2>
      ${steps}
    </article>
    <article>
      <p class="disclaimer">${escapeHtml(review.disclaimer)}</p>
    </article>`;
  results.hidden = false;
}

function setStatus(message, isError) {
  status.textContent = message;
  status.classList.toggle("error", Boolean(isError));
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

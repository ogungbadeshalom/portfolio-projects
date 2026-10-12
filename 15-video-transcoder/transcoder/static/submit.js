// Drag-and-drop submit on the landing page.
const zone = document.getElementById("drop");
const form = document.getElementById("upload-form");
const file = document.getElementById("file");
const result = document.getElementById("result");

zone.addEventListener("dragover", (e) => {
  e.preventDefault();
  zone.classList.add("over");
});
zone.addEventListener("dragleave", () => zone.classList.remove("over"));
zone.addEventListener("drop", (e) => {
  e.preventDefault();
  zone.classList.remove("over");
  if (e.dataTransfer.files.length) {
    file.files = e.dataTransfer.files;
    submit();
  }
});
zone.addEventListener("click", (e) => {
  if (e.target.id !== "file") file.click();
});
file.addEventListener("change", submit);

async function submit() {
  if (!file.files.length) return;
  const fd = new FormData();
  fd.append("file", file.files[0]);
  fd.append("resolutions", document.getElementById("resolutions").value || "480,720,1080");
  result.textContent = "Uploading and enqueueing…";
  try {
    const resp = await fetch("/api/jobs", { method: "POST", body: fd });
    const data = await resp.json();
    result.innerHTML = `Job <a href="/jobs">${data.id}</a> enqueued — resolutions ${data.resolutions.join(", ")}.`;
  } catch (err) {
    result.textContent = "Submission failed: " + err.message;
  }
}
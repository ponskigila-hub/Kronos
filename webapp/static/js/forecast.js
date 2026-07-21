(function () {
  const tabBtns = document.querySelectorAll(".tab-btn");
  const panels = document.querySelectorAll(".tab-panel");

  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      tabBtns.forEach((b) => b.classList.remove("active"));
      panels.forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
    });
  });

  const fileInput = document.getElementById("fileInput");
  const dropZone = document.getElementById("dropZone");
  const fileLabel = document.getElementById("fileLabel");

  if (fileInput && dropZone) {
    fileInput.addEventListener("change", () => {
      if (fileInput.files.length) {
        fileLabel.innerHTML = "Selected: <strong>" + fileInput.files[0].name + "</strong>";
      }
    });
    ["dragenter", "dragover"].forEach((evt) =>
      dropZone.addEventListener(evt, (e) => {
        e.preventDefault();
        dropZone.classList.add("drag");
      })
    );
    ["dragleave", "drop"].forEach((evt) =>
      dropZone.addEventListener(evt, (e) => {
        e.preventDefault();
        dropZone.classList.remove("drag");
      })
    );
    dropZone.addEventListener("drop", (e) => {
      if (e.dataTransfer.files.length) {
        fileInput.files = e.dataTransfer.files;
        fileLabel.innerHTML = "Selected: <strong>" + e.dataTransfer.files[0].name + "</strong>";
      }
    });
  }
})();

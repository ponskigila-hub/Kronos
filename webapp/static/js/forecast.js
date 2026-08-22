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

  const detailedCheckbox = document.getElementById("detailed");
  const tickerForm = document.getElementById("tickerForm");
  if (detailedCheckbox && tickerForm) {
    const updateLoadingMessage = () => {
      tickerForm.dataset.loadingMessage = detailedCheckbox.checked
        ? "Running detailed forecast — several sampled paths, this takes noticeably longer…"
        : "Running forecast…";
    };
    detailedCheckbox.addEventListener("change", updateLoadingMessage);
    updateLoadingMessage();
  }

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

  // ---------------------------------------------------------------------
  // Background job submission + polling for both forms. Both
  // /forecast/ticker and /forecast/csv now return {"job_id": "..."}
  // immediately instead of blocking the request for the full Kronos
  // inference time, so the page stays responsive (and the loading
  // overlay reflects real progress, not a frozen request) the same way
  // the chat page already works -- see webapp/static/js/chat.js.
  // ---------------------------------------------------------------------
  const POLL_INTERVAL_MS = 1200;

  const resultSection = document.getElementById("resultSection");
  const resultTag = document.getElementById("resultTag");
  const resultText = document.getElementById("resultText");
  const chartFrame = document.getElementById("chartFrame");

  function clearInlineError(form) {
    const existing = form.querySelector(".flash-error");
    if (existing) existing.remove();
  }

  function showInlineError(form, message) {
    clearInlineError(form);
    const el = document.createElement("div");
    el.className = "flash flash-error";
    el.textContent = message;
    form.prepend(el);
  }

  function showResult(data) {
    if (resultTag) resultTag.textContent = data.ticker || "";
    if (resultText) resultText.textContent = data.text || "";
    if (chartFrame) {
      if (data.image_url) {
        chartFrame.style.display = "";
        chartFrame.innerHTML =
          '<img src="' + data.image_url + '" alt="Forecast chart for ' +
          (data.ticker || "") + '">';
      } else {
        chartFrame.style.display = "none";
        chartFrame.innerHTML = "";
      }
    }
    if (resultSection) {
      resultSection.style.display = "";
      resultSection.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  function pollJob(jobId, form, submitBtn, originalBtnText) {
    fetch("/forecast/job/" + jobId)
      .then((r) => r.json())
      .then((data) => {
        if (data.status === "pending") {
          setTimeout(() => pollJob(jobId, form, submitBtn, originalBtnText), POLL_INTERVAL_MS);
          return;
        }
        window.KronosLoading && window.KronosLoading.hide();
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = originalBtnText;
        }
        if (data.status === "done") {
          showResult(data);
        } else if (data.status === "error") {
          showInlineError(form, data.message || "Something went wrong.");
        } else {
          showInlineError(form, "Lost track of that job -- please try again.");
        }
      })
      .catch(() => {
        // A transient network hiccup while polling shouldn't give up
        // immediately -- the background job is still running server-side
        // regardless of whether this particular poll succeeded.
        setTimeout(() => pollJob(jobId, form, submitBtn, originalBtnText), POLL_INTERVAL_MS);
      });
  }

  function wireBackgroundForm(form) {
    if (!form) return;
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      clearInlineError(form);

      const submitBtn = form.querySelector('button[type="submit"]');
      const originalBtnText = submitBtn ? submitBtn.textContent : null;
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Working…";
      }
      window.KronosLoading && window.KronosLoading.show(form.dataset.loadingMessage);

      fetch(form.action, { method: "POST", body: new FormData(form) })
        .then((r) => r.json().then((data) => ({ ok: r.ok, data })))
        .then(({ ok, data }) => {
          if (!ok || data.error) {
            window.KronosLoading && window.KronosLoading.hide();
            if (submitBtn) {
              submitBtn.disabled = false;
              submitBtn.textContent = originalBtnText;
            }
            showInlineError(form, data.error || "Request failed.");
            return;
          }
          pollJob(data.job_id, form, submitBtn, originalBtnText);
        })
        .catch(() => {
          window.KronosLoading && window.KronosLoading.hide();
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = originalBtnText;
          }
          showInlineError(form, "Couldn't reach the server -- please try again.");
        });
    });
  }

  wireBackgroundForm(tickerForm);
  wireBackgroundForm(document.getElementById("csvForm"));
})();


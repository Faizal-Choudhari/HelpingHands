document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form[onsubmit]").forEach(form => {
    form.addEventListener("submit", e => {
      if (!confirm("Are you sure you want to continue?")) e.preventDefault();
    });
  });
});

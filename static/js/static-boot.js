(function () {
  const meta = document.querySelector('meta[name="jobboards-base"]');
  let base = meta ? meta.content : "./";
  if (!base.endsWith("/")) base += "/";
  window.JobBoardsBase = base;
  window.JobBoardsStatic = true;

  window.JobBoardsAsset = function (path) {
    return base + "static/" + path.replace(/^\//, "");
  };

  window.JobBoardsDataUrl = function (name) {
    return base + "data/" + name;
  };

  window.JobBoardsPageUrl = function (page) {
    return base + page;
  };
})();

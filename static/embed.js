// Adds the "Lab Helpdesk" button and chat panel to any page:
// <script src="http://<server>:8000/static/embed.js"></script>
(function () {
  var script = document.currentScript;
  var origin = new URL(script.src).origin;          // the LabAssist API server

  var button = document.createElement("button");
  button.textContent = "Lab Helpdesk";
  button.setAttribute("aria-label", "Open the CSIS ICT Laboratory Helpdesk");
  button.style.cssText = "position:fixed;right:20px;bottom:20px;z-index:99999;padding:12px 18px;" +
    "border:none;border-radius:6px;background:#310098;color:#fff;font:600 15px sans-serif;" +
    "cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,.25)";

  var frame = document.createElement("iframe");
  frame.src = origin + "/widget";
  frame.title = "CSIS ICT Laboratory Helpdesk";
  frame.style.cssText = "position:fixed;right:20px;bottom:76px;z-index:99999;width:380px;height:560px;" +
    "max-width:calc(100vw - 40px);max-height:calc(100vh - 100px);border:1px solid #DAD7E8;" +
    "border-radius:8px;background:#fff;display:none;box-shadow:0 2px 10px rgba(0,0,0,.18)";

  function show(open) {
    frame.style.display = open ? "block" : "none";
    button.textContent = open ? "Close helpdesk" : "Lab Helpdesk";
  }
  button.addEventListener("click", function () { show(frame.style.display === "none"); });

  // lets the page open the chat, e.g. LabAssist.open()
  window.LabAssist = { open: function () { show(true); }, close: function () { show(false); } };

  document.body.appendChild(frame);
  document.body.appendChild(button);
})();

const fs = require("fs");
const code = fs.readFileSync("static/formatter.js", "utf8");
const input = [
  "124200 blue w9 $60000",
  "124200 blue w9 $60000",
  "124200 blue w9/2026 60000",
  "126333 GREEN ROM JUB n6/2026 151000",
  "126333 GREEN ROM JUB N6/2026 151000",
  "126300 GREEN Oys n7/2026 85000",
  "120w"
].join("\n");
const store = { inputData: { value: input }, outputResult: { innerText: "" } };
global.document = { getElementById: id => store[id] };
global.alert = () => {};
eval(code);
processWatchData();
console.log(store.outputResult.innerText);

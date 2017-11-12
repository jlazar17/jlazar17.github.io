 <script>
    var COLOR_CHANGE_INTERVAL = 100
    var COLORS = ["red", "orange", "yellow", "green", "blue", "indigo", "violet"];
    var h1 = document.getElementsByTagName("h1");
    var h2 = document.getElementsByTagName("h2");
    function getDifferentRandomColor(text) {
        var i = COLORS.indexOf(text.style.color);
        i = (i + 1 + Math.floor(Math.random() * (COLORS.length - 1))) % COLORS.length;
        return COLORS[i];
    }
    function randomColorize(headings) {
        for (var i=0; i<headings.length; i++) {
            headings[i].style.color = getDifferentRandomColor(headings[i]);
        }
    }
    function randomlyColorizeHeadings() {
        randomColorize(h1);
        randomColorize(h2);
    }
    function pleaseStop() {
        emoji = document.getElementsByClassName("flying-emoji");
        for (var i=0; i<emoji.length; i++) {
            emoji[i].style.display = "none";
        }
        window.clearInterval(KILL_ME_NOW)
    }
    KILL_ME_NOW = window.setInterval(randomlyColorizeHeadings, COLOR_CHANGE_INTERVAL);
</script>

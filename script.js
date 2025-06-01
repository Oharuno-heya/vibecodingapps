class PomodoroTimer {
    constructor() {
        this.workTime = 25 * 60; // 25分を秒に変換
        this.breakTime = 5 * 60; // 5分を秒に変換
        this.isWorking = true; // 作業中か休憩中かのフラグ
        this.isRunning = false; // タイマーが実行中かのフラグ
        this.timer = null;
        
        // DOM要素の取得
        this.$timer = document.getElementById('timer');
        this.$startBtn = document.getElementById('startBtn');
        this.$stopBtn = document.getElementById('stopBtn');
        this.$resetBtn = document.getElementById('resetBtn');
        this.$workTime = document.getElementById('workTime');
        this.$breakTime = document.getElementById('breakTime');
        
        // イベントリスナーの設定
        this.$startBtn.addEventListener('click', () => this.start());
        this.$stopBtn.addEventListener('click', () => this.stop());
        this.$resetBtn.addEventListener('click', () => this.reset());
        this.$workTime.addEventListener('change', () => this.updateWorkTime());
        this.$breakTime.addEventListener('change', () => this.updateBreakTime());
    }

    start() {
        if (this.isRunning) return;
        
        this.isRunning = true;
        this.$startBtn.disabled = true;
        this.$stopBtn.disabled = false;
        this.$resetBtn.disabled = true;
        
        this.runTimer();
    }

    stop() {
        this.isRunning = false;
        this.$startBtn.disabled = false;
        this.$stopBtn.disabled = true;
        this.$resetBtn.disabled = false;
        
        if (this.timer) {
            clearInterval(this.timer);
        }
    }

    reset() {
        this.stop();
        this.isWorking = true;
        this.workTime = this.$workTime.value * 60;
        this.breakTime = this.$breakTime.value * 60;
        this.$timer.textContent = this.formatTime(this.workTime);
        this.$startBtn.disabled = false;
        this.$stopBtn.disabled = true;
        this.$resetBtn.disabled = true;
    }

    runTimer() {
        this.timer = setInterval(() => {
            if (this.isWorking) {
                this.workTime--;
                this.$timer.textContent = this.formatTime(this.workTime);
                
                if (this.workTime <= 0) {
                    this.isWorking = false;
                    this.workTime = 25 * 60;
                    this.breakTime = this.$breakTime.value * 60;
                    this.$timer.textContent = this.formatTime(this.breakTime);
                }
            } else {
                this.breakTime--;
                this.$timer.textContent = this.formatTime(this.breakTime);
                
                if (this.breakTime <= 0) {
                    this.isWorking = true;
                    this.breakTime = 5 * 60;
                    this.workTime = this.$workTime.value * 60;
                    this.$timer.textContent = this.formatTime(this.workTime);
                }
            }
        }, 1000);
    }

    formatTime(seconds) {
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = seconds % 60;
        return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
    }

    updateWorkTime() {
        const value = parseInt(this.$workTime.value);
        if (value >= 1) {
            this.workTime = value * 60;
            if (!this.isRunning) {
                this.$timer.textContent = this.formatTime(this.workTime);
            }
        }
    }

    updateBreakTime() {
        const value = parseInt(this.$breakTime.value);
        if (value >= 1) {
            this.breakTime = value * 60;
        }
    }
}

// インスタンスの作成
const pomodoroTimer = new PomodoroTimer();

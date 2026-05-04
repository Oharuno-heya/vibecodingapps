const reserveBtn = document.getElementById('reserveBtn');
const reserveMessage = document.getElementById('reserveMessage');

if (reserveBtn && reserveMessage) {
  reserveBtn.addEventListener('click', () => {
    reserveMessage.textContent = 'ご予約はお電話（03-1234-5678）または店頭にて承っております。';
  });
}

# ZiolelloBet Telegram Bot

Bot Telegram per la gestione automatica delle richieste di accesso al canale/gruppo ZiolelloBet.

## Funzioni principali

- Approva automaticamente le richieste di ingresso
- Invia messaggio privato di benvenuto
- Invia follow-up automatico dopo un tempo configurabile
- Salva utenti approvati in database SQLite
- Mostra statistiche con comando `/stats`
- Invia report manuale con comando `/report`
- Invia report automatico ogni 2 ore agli admin
- Esporta utenti approvati in CSV con comando `/export`

---

## File del progetto

Il progetto deve contenere questi file:

```text
bot.py
requirements.txt
README.md
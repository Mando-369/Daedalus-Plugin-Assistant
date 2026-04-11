# Daedalus Plugin Assistant - Setup TODO

## Git Repo Init (run in Terminal)

```bash
cd ~/Dev/"Plugin Manager & Assistant"
rm -f .git/index.lock
git init && git branch -M main
git add -A
git config user.email "tomman1976@gmail.com"
git config user.name "Thomas Mandolini"
git commit -m "Initial commit: Daedalus Plugin Assistant"
git remote add origin https://github.com/Mando-369/Daedalus-Plugin-Assistant.git
git push -u origin main
```

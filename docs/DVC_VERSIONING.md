# Versionnement des données avec DVC

Le fichier `data/raw/course_catalog.csv` contient uniquement des données
pédagogiques synthétiques. Son contenu est stocké dans le cache DVC et dans le
remote de test local ; Git ne suit que son petit fichier pointeur `.dvc`.

## Commandes courantes

```powershell
.\.venv\Scripts\dvc.exe status
.\.venv\Scripts\dvc.exe remote list
.\.venv\Scripts\dvc.exe add data\raw\course_catalog.csv
.\.venv\Scripts\dvc.exe push
```

Après `dvc add`, il faut normalement créer un commit Git contenant le fichier
`data/raw/course_catalog.csv.dvc`. Aucun commit n'est créé automatiquement dans
ce projet.

Les métadonnées peuvent être préparées dans l'index Git sans créer de commit :

```powershell
git add .dvc .dvcignore data/raw/.gitignore data/raw/course_catalog.csv.dvc
```

## Restaurer la version courante

Après un clonage ou si le fichier de travail a disparu :

```powershell
.\.venv\Scripts\dvc.exe pull
```

`dvc pull` télécharge l'objet référencé par le fichier `.dvc` courant et restaure
le dataset dans l'espace de travail.

## Restaurer une ancienne version

DVC utilise l'historique Git des fichiers `.dvc` pour identifier les versions.
Une fois les versions réellement validées par des commits humains :

```powershell
git checkout <commit-ou-tag> -- data/raw/course_catalog.csv.dvc
.\.venv\Scripts\dvc.exe checkout data\raw\course_catalog.csv.dvc
```

Pour revenir à la version de la branche courante :

```powershell
git restore data/raw/course_catalog.csv.dvc
.\.venv\Scripts\dvc.exe checkout data\raw\course_catalog.csv.dvc
```

## Passer plus tard à un stockage partagé

Le remote `local-storage` est uniquement destiné aux essais sur cette machine.
L'équipe pourra le remplacer, par exemple, par S3, Azure Blob Storage, Google
Cloud Storage, SSH ou un répertoire réseau :

```powershell
.\.venv\Scripts\dvc.exe remote add -d shared-storage <URL-DU-STOCKAGE>
.\.venv\Scripts\dvc.exe push
```

Les URL non sensibles peuvent être partagées dans `.dvc/config`. Les identifiants
et chemins de secrets doivent être configurés avec `--local`, ce qui les place
dans `.dvc/config.local`, ignoré par Git :

```powershell
.\.venv\Scripts\dvc.exe remote modify --local shared-storage <option> <valeur>
```

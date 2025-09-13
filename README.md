# evaluation form service

# Git Workflow - Feature Branch Flow

main        # Stable version (Prod)
develop     # Current development 
feature/*   # New functions
bugfix/*    # Bug fixing
hotfix/*    # Immediate fixing


Rules of Operation
1. Starting work on a new feature

        git checkout develop
        git pull origin develop

# create new branch function
    git checkout -b feature/function-name

2. Branch naming convention

        feature/user-authentication - New features
        feature/evaluation-forms - main components компоненти
        bugfix/fix-validation-error - BugFix
        hotfix/security-patch - ImmediateFix

# Regular commits with descriptive messages
git add .
git commit -m "Add: model User with base fields"
# Push to GitHub
git push -u origin feature/feature-name

3. Pull Request
Create PR з feature/feature-name to develop
Fill description for example:

   ## What added or changed
   - [ ] Change description
   
   ## Tests
   - [ ] Written tests
   - [ ] Manual tests done
   
   ## Checklist
   - [ ] Code reviewed
   - [ ] Documentation updated

- add reviewer (another developer)
- wait approve
- merge after approve

5. After merge
# back to develop
git checkout develop
git pull origin develop

# Delete local branch feature
git branch -d feature/feature-name
6. Commits

        Add: New feature
        Fix: BugFix
        Update: Update current code
        Remove: code delete

# For example:

    Add: User registration API endpoint
    Fix: validation error in evaluation form
    Update: authentication middleware
from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from apps.accounts.models import Learner
from django.contrib.auth.models import Group

class AuthentikOIDCBackend(OIDCAuthenticationBackend):
    def create_user(self, claims):
        user = super(AuthentikOIDCBackend, self).create_user(claims)
        self.update_user_info(user, claims)
        return user

    def update_user(self, user, claims):
        self.update_user_info(user, claims)
        return user

    def update_user_info(self, user, claims):
        # DEBUG: See what Authentik is sending us!
        print("--- OIDC CLAIMS RECEIVED ---")
        print(claims)
        print("---------------------------")
        
        # Update or Create Learner Profile
        learner, created = Learner.objects.get_or_create(
            email=user.email,
            defaults={
                'auth_user_id': str(claims.get('sub')),
                'full_name': f"{user.first_name} {user.last_name}".strip() or user.email,
            }
        )

        groups = claims.get('groups', [])
        
        # Admin logic: Check if user is in 'Admins' group in Authentik OR is marked admin in DB
        if 'Admins' in groups or learner.is_admin:
            user.is_staff = True
            user.is_superuser = True
            if not learner.is_admin:
                learner.is_admin = True
                learner.save()
        else:
            user.is_staff = False
            user.is_superuser = False
        
        user.first_name = claims.get('given_name', '')
        user.last_name = claims.get('family_name', '')
        user.save()

        # Final sync of Learner profile
        learner.auth_user_id = str(claims.get('sub'))
        learner.full_name = f"{user.first_name} {user.last_name}".strip() or user.email
        learner.save()

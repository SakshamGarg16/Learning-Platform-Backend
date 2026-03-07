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
        # Authentik typically sends groups in the 'groups' claim
        groups = claims.get('groups', [])
        
        # Admin logic: Check if user is in 'Admins' group in Authentik
        if 'Admins' in groups:
            user.is_staff = True
            user.is_superuser = True
        else:
            user.is_staff = False
            user.is_superuser = False
        
        user.first_name = claims.get('given_name', '')
        user.last_name = claims.get('family_name', '')
        user.save()

        # Update or Create Learner Profile
        learner, created = Learner.objects.update_or_create(
            email=user.email,
            defaults={
                'auth_user_id': claims.get('sub'),
                'full_name': f"{user.first_name} {user.last_name}".strip() or user.email,
            }
        )

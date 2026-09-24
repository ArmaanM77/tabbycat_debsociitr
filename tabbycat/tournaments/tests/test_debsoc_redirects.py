from django.test import TestCase
from django.urls import reverse

from tournaments.models import Tournament


class LatestDebSocTournamentRedirectTests(TestCase):
    def create_tournament(self, slug, *, active=True):
        return Tournament.objects.create(
            name=slug,
            short_name=slug,
            slug=slug,
            active=active,
        )

    def test_apd_redirects_to_newest_active_month(self):
        self.create_tournament('apd-july-26')
        newest = self.create_tournament('apd-august-26')
        self.create_tournament('apd-september-26', active=False)

        response = self.client.get(reverse('latest-apd-tournament'))

        self.assertRedirects(response, newest.get_public_url(), fetch_redirect_response=False)

    def test_bpd_redirects_to_newest_active_month(self):
        newest = self.create_tournament('bpd-august-26')

        response = self.client.get(reverse('latest-bpd-tournament'))

        self.assertRedirects(response, newest.get_public_url(), fetch_redirect_response=False)

    def test_missing_format_returns_to_site_index(self):
        response = self.client.get(reverse('latest-apd-tournament'))

        self.assertRedirects(response, reverse('tabbycat-index'), fetch_redirect_response=False)

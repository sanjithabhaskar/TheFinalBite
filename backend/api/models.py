# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey and OneToOneField has `on_delete` set to the desired behavior
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from django.db import models
from django.contrib.postgres.fields import ArrayField

class DiningGroups(models.Model):
    invite_code = models.TextField(unique=True)
    name = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    host_member = models.ForeignKey('Members', models.DB_SET_NULL, blank=True, null=True, related_name='hosted_groups')
    started_at = models.DateTimeField(blank=True, null=True)
    deck_ids = ArrayField(models.IntegerField(), default=list, blank=True)

    class Meta:
        managed = False
        db_table = 'dining_groups'


class GroupMatches(models.Model):
    group_id = models.IntegerField(blank=True, null=True)
    restaurant_id = models.IntegerField(blank=True, null=True)
    yes_votes = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False  # Created from a view.
        db_table = 'group_matches'


class Members(models.Model):
    group = models.ForeignKey(DiningGroups, models.DB_CASCADE, related_name='members')
    name = models.TextField()
    max_entree_budget = models.DecimalField(max_digits=6, decimal_places=2)
    dietary_restrictions = ArrayField(models.TextField(), default=list, blank=True)
    cuisine_prefs = ArrayField(models.TextField(), default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    token = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'members'


class MenuItems(models.Model):
    restaurant = models.ForeignKey('Restaurants', models.DB_CASCADE)
    section = models.TextField(blank=True, null=True)
    category = models.TextField()
    name = models.TextField()
    description = models.TextField(blank=True, null=True)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    dietary_tags = models.TextField(blank=True, null=True)  # This field type is a guess.

    class Meta:
        managed = False
        db_table = 'menu_items'


class Restaurants(models.Model):
    place_id = models.TextField(unique=True)
    name = models.TextField()
    address = models.TextField(blank=True, null=True)
    neighborhood = models.TextField(blank=True, null=True)
    lat = models.FloatField(blank=True, null=True)
    lng = models.FloatField(blank=True, null=True)
    primary_type = models.TextField(blank=True, null=True)
    types = ArrayField(models.TextField(), blank=True, null=True)
    cuisines = ArrayField(models.TextField(), blank=True, null=True)
    dietary_tags = ArrayField(models.TextField(), blank=True, null=True)
    
    website = models.TextField(blank=True, null=True)
    rating = models.DecimalField(max_digits=2, decimal_places=1, blank=True, null=True)
    rating_count = models.IntegerField(blank=True, null=True)
    google_price_level = models.TextField(blank=True, null=True)
    google_price_min = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    google_price_max = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    prix_fixe_price = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    median_entree_price = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    min_entree_price = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    max_entree_price = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    menu_url = models.TextField(blank=True, null=True)
    menu_style = models.TextField(blank=True, null=True)
    entree_count = models.IntegerField(blank=True, null=True)
    menu_status = models.TextField()
    menu_note = models.TextField(blank=True, null=True)
    menu_last_verified = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    menu_url_override = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'restaurants'


class Swipes(models.Model):
    member = models.ForeignKey(Members, models.DB_CASCADE)
    restaurant = models.ForeignKey(Restaurants, models.DB_CASCADE)
    liked = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'swipes'
        unique_together = (('member', 'restaurant'),)
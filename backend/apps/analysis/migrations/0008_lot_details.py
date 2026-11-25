from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('analysis', '0007_flow_activity'),
    ]

    operations = [
        migrations.AddField(model_name='analysissession', name='lot_date',
                            field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name='analysissession', name='lot_weight_kg',
                            field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name='analysissession', name='supplier',
                            field=models.CharField(blank=True, max_length=120)),
        migrations.AddField(model_name='analysissession', name='pond',
                            field=models.CharField(blank=True, max_length=60)),
        migrations.AddField(model_name='analysissession', name='harvest_date',
                            field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name='analysissession', name='product_presentation',
                            field=models.CharField(blank=True, choices=[('entero', 'Entero'), ('sin_cabeza', 'Sin cabeza'), ('pelado', 'Pelado')], max_length=16)),
        migrations.AddField(model_name='analysissession', name='declared_size',
                            field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name='analysissession', name='expected_count',
                            field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.AddField(model_name='analysissession', name='product_temperature_c',
                            field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name='analysissession', name='notes',
                            field=models.TextField(blank=True, max_length=500)),
    ]

from django.db import models


class SqlFunDefinition(models.Model):
    function_name = models.CharField(max_length=255, unique=True)
    sql_definition = models.TextField()
    app_label = models.CharField(max_length=255)

    def __str__(self):
        return self.function_name

    class Meta:
        app_label = 'sqlfun'

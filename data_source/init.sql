-- Fichier d'initialisation de la base de données pour le POC Churn Prediction (avec Audit)
-- IMPORTANT : Toutes les données ici sont SYNTHÉTIQUES et à but de démonstration.

-- Désactiver les messages NOTICE pour alléger les logs Docker au démarrage
SET client_min_messages TO WARNING;

-- Créer les tables métier si elles n'existent pas
CREATE TABLE IF NOT EXISTS customers (
    customer_id SERIAL PRIMARY KEY,
    name VARCHAR(100), -- Nom synthétique
    last_activity_days INT,
    complaints_count INT,
    feedback_text TEXT, -- Feedback synthétique
    consent_given BOOLEAN DEFAULT TRUE, -- Flag de consentement pour la démo de gouvernance
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE customers IS 'Table contenant les informations (synthétiques) des clients.';
COMMENT ON COLUMN customers.consent_given IS 'Flag indiquant si le client (synthétique) a donné son consentement pour l''analyse de feedback par IA.';

CREATE TABLE IF NOT EXISTS feedback_analysis (
    analysis_id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customers(customer_id) UNIQUE, -- Une seule analyse par client pour ce POC
    feedback_summary TEXT,
    sentiment VARCHAR(50), -- Ex: Positive, Negative, Neutral, Mixed
    key_topics TEXT,       -- Ex: "Fees, Mobile App Interface"
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE feedback_analysis IS 'Résultats de l''analyse NLP (via Groq) des feedbacks clients.';

CREATE TABLE IF NOT EXISTS predictions (
    prediction_id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customers(customer_id) UNIQUE, -- Une seule prédiction par client pour ce POC
    churn_probability FLOAT CHECK (churn_probability >= 0 AND churn_probability <= 1), -- Probabilité entre 0 et 1
    predicted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE predictions IS 'Résultats de la prédiction de churn par le modèle ML.';
COMMENT ON COLUMN predictions.churn_probability IS 'Probabilité que le client quitte la banque (0=reste, 1=part).';


CREATE TABLE IF NOT EXISTS actions (
    action_id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customers(customer_id) UNIQUE, -- Une seule action par client pour ce POC
    segment VARCHAR(50), -- Ex: Low Risk, Medium Risk, High Risk
    recommended_action TEXT, -- Action générée par Groq
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE actions IS 'Actions de rétention recommandées par l''agent IA.';
COMMENT ON COLUMN actions.segment IS 'Segment de risque basé sur la probabilité de churn.';
COMMENT ON COLUMN actions.recommended_action IS 'Texte de l''action de rétention suggérée par le LLM.';


-- ======= Table d'Audit pour la Gouvernance =======
CREATE TABLE IF NOT EXISTS audit_log (
    log_id SERIAL PRIMARY KEY,
    log_timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, -- Timestamp précis avec timezone
    agent_name VARCHAR(50) NOT NULL,        -- Nom de l'agent ('nlp', 'prediction', 'action')
    event_type VARCHAR(100) NOT NULL,       -- Type d'événement ('CONSENT_CHECK', 'ANONYMIZE_START', 'GROQ_CALL_END', etc.)
    status VARCHAR(20) DEFAULT 'INFO',      -- Statut ('INFO', 'SUCCESS', 'FAILURE', 'WARNING', 'ERROR')
    customer_id INT NULL,                   -- ID client lié (optionnel)
    details TEXT NULL                       -- Détails supplémentaires (message, durée, etc.)
);
COMMENT ON TABLE audit_log IS 'Trace des événements importants exécutés par les agents IA pour l''audit et la gouvernance.';
COMMENT ON COLUMN audit_log.event_type IS 'Catégorie de l''événement logué (ex: appel API, vérification, sauvegarde BDD).';
COMMENT ON COLUMN audit_log.status IS 'Résultat de l''événement (succès, échec, info, etc.).';
COMMENT ON COLUMN audit_log.details IS 'Informations contextuelles additionnelles pour l''événement.';


-- Index pour améliorer les requêtes sur la table d'audit
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(log_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_event_type ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_agent_name ON audit_log(agent_name);
-- Fin Table d'Audit

-- Insertion de données clients SYNTHÉTIQUES si la table est vide
-- Utiliser une structure qui évite les doublons si le script est exécuté plusieurs fois (bien que docker-entrypoint-initdb.d le gère)
DO $$
DECLARE
    -- Tableaux de noms et prénoms synthétiques pour la génération de données
    prenoms TEXT[] := ARRAY['Jean', 'Marie', 'Pierre', 'Sophie', 'Thomas', 'Isabelle', 'François', 'Emilie', 
                            'Nicolas', 'Nathalie', 'Michel', 'Claire', 'Philippe', 'Laura', 'André', 'Caroline', 
                            'Paul', 'Julie', 'Jacques', 'Emma', 'Lucas', 'Léa', 'Antoine', 'Camille', 'Julien', 
                            'Sarah', 'David', 'Aurélie', 'Marc', 'Céline', 'Alexandre', 'Elodie', 'Eric', 'Chloé', 
                            'Patrick', 'Valérie', 'Christophe', 'Sandrine', 'Sébastien', 'Laure', 'Guillaume', 
                            'Anne', 'Benoît', 'Catherine', 'Olivier', 'Stéphanie', 'Vincent', 'Mélanie', 'Daniel', 'Hélène'];
    
    noms TEXT[] := ARRAY['Martin', 'Bernard', 'Dubois', 'Thomas', 'Robert', 'Richard', 'Petit', 'Durand', 
                         'Leroy', 'Moreau', 'Simon', 'Laurent', 'Lefebvre', 'Michel', 'Garcia', 'David', 
                         'Bertrand', 'Roux', 'Vincent', 'Fournier', 'Morel', 'Girard', 'Andre', 'Lefevre', 
                         'Mercier', 'Dupont', 'Lambert', 'Bonnet', 'Francois', 'Martinez', 'Legrand', 'Garnier', 
                         'Faure', 'Rousseau', 'Blanc', 'Guerin', 'Muller', 'Henry', 'Roussel', 'Nicolas', 
                         'Perrin', 'Morin', 'Mathieu', 'Clement', 'Gauthier', 'Dumont', 'Lopez', 'Fontaine', 
                         'Chevalier', 'Robin'];
    
    -- Tableaux de feedbacks synthétiques
    feedbacks_positifs TEXT[] := ARRAY[
        'Très satisfait du service client. Réactivité exemplaire!',
        'Application mobile intuitive et performante. Je fais toutes mes opérations sans difficulté.',
        'Les conseillers sont vraiment à l''écoute et professionnels.',
        'Excellente expérience avec cette banque depuis 3 ans maintenant.',
        'Les taux proposés sont compétitifs, je recommande cette banque.',
        'J''apprécie la simplicité des opérations quotidiennes.',
        'Le service en ligne est disponible 24/7, c''est pratique.',
        'Aucun souci avec ma carte bancaire, tout fonctionne parfaitement.',
        'L''ouverture de compte a été rapide et sans paperasse excessive.',
        'Ma conseillère Mme Dupont est très attentive à mes besoins.'
    ];
    
    feedbacks_neutres TEXT[] := ARRAY[
        'Service correct mais rien d''exceptionnel.',
        'L''appli mobile pourrait être améliorée au niveau de la navigation.',
        'Délais standards pour les virements internationaux.',
        'Je n''ai pas eu de problèmes majeurs jusqu''à présent.',
        'Les frais sont dans la moyenne des autres banques.',
        'Le temps d''attente au téléphone est acceptable.',
        'Interface du site web un peu datée mais fonctionnelle.',
        'Pas de soucis particuliers avec mon compte.',
        'RIB difficile à trouver dans l''espace client.',
        'Service basique qui répond aux attentes minimales.'
    ];
    
    feedbacks_negatifs TEXT[] := ARRAY[
        'Délais inacceptables pour les virements! Plus de 5 jours pour un simple transfert.',
        'Impossible de joindre le service client au numéro 0123456789. Attente interminable.',
        'Frais cachés de 35€ prélevés sans avertissement. Je vais changer de banque!',
        'Application qui plante régulièrement. Mise à jour urgente nécessaire.',
        'Mon conseiller ne répond jamais à mes emails. Je me sens délaissé.',
        'Erreur sur mon relevé de compte non corrigée depuis 2 mois malgré mes réclamations.',
        'Conditions tarifaires modifiées sans préavis. C''est inadmissible!',
        'Service client incompétent, on me donne une information différente à chaque appel.',
        'Clôture de compte extrêmement compliquée, on me fait tourner en rond.',
        'Découvert refusé alors que je suis client depuis 10 ans. Je suis très déçu.'
    ];
    
    -- Variables pour la génération aléatoire
    i INTEGER;
    nom_complet TEXT;
    last_activity INTEGER;
    complaints INTEGER;
    feedback TEXT;
    consent BOOLEAN;
    feedback_type TEXT;
BEGIN
    -- Vérifier si la table est vide avant d'insérer
    IF NOT EXISTS (SELECT 1 FROM customers) THEN
        -- Insertion des données originales pour la compatibilité
        INSERT INTO customers (name, last_activity_days, complaints_count, feedback_text, consent_given) VALUES
        ('Alice Dubois (Synth)', 5, 0, 'Service rapide et efficace, je suis très satisfaite de ma banque. L application mobile est claire.', TRUE),
        ('Bob Martin (Synth)', 95, 3, 'Le virement international a pris 10 jours! Le service client au 0123456789 etait injoignable. Je pense partir chez BankPro.', TRUE),
        ('Charlie Durand (Synth)', 30, 1, 'Interface appli mobile peu claire pour trouver le RIB. Mon conseiller M. Dupont est reactif.', TRUE),
        ('Diana Lefevre (Synth)', 150, 5, 'Des frais de 50eur preleves sans prevenir sur mon compte 987654321! C est inadmissible, je vais cloturer mon compte demain. Adresse: 1 rue de la Paix', TRUE),
        ('Ethan Moreau (Synth)', 15, 0, NULL, TRUE), -- Pas de feedback
        ('Fiona Petit (Synth)', 210, 4, 'J ai envoye un email a service.client@banque.fr pour une reclamation sur les frais, jamais eu de reponse. Tres decue.', FALSE), -- !! CONSENTEMENT REFUSÉ !!
        ('Gabriel Leroy (Synth)', 60, 0, 'Tout fonctionne bien, ras.', TRUE);
        
        -- Génération de 200+ clients synthétiques supplémentaires
        FOR i IN 1..200 LOOP
            -- Génération d'un nom complet aléatoire
            nom_complet := prenoms[1 + floor(random() * array_length(prenoms, 1))] || ' ' || 
                          noms[1 + floor(random() * array_length(noms, 1))] || ' (Synth)';
            
            -- Génération de la dernière activité (entre 1 et 365 jours)
            last_activity := 1 + floor(random() * 365);
            
            -- Génération du nombre de plaintes (entre 0 et 5)
            complaints := floor(random() * 6);
            
            -- Détermination du type de feedback en fonction de l'activité et des plaintes
            -- Pour créer une corrélation entre activité, plaintes et sentiment du feedback
            IF last_activity > 180 OR complaints >= 3 THEN
                feedback_type := 'negatif';
            ELSIF last_activity > 60 OR complaints >= 1 THEN
                feedback_type := 'neutre';
            ELSE
                feedback_type := 'positif';
            END IF;
            
            -- Sélection aléatoire d'un feedback du type correspondant
            IF feedback_type = 'negatif' THEN
                feedback := feedbacks_negatifs[1 + floor(random() * array_length(feedbacks_negatifs, 1))];
            ELSIF feedback_type = 'neutre' THEN
                feedback := feedbacks_neutres[1 + floor(random() * array_length(feedbacks_neutres, 1))];
            ELSE
                feedback := feedbacks_positifs[1 + floor(random() * array_length(feedbacks_positifs, 1))];
            END IF;
            
            -- 10% des clients n'ont pas de feedback
            IF random() < 0.1 THEN
                feedback := NULL;
            END IF;
            
            -- 15% des clients n'ont pas donné leur consentement
            consent := random() >= 0.15;
            
            -- Insertion du client dans la table
            INSERT INTO customers (
                name, 
                last_activity_days, 
                complaints_count, 
                feedback_text, 
                consent_given
            ) VALUES (
                nom_complet,
                last_activity,
                complaints,
                feedback,
                consent
            );
        END LOOP;
        
        RAISE NOTICE 'Données clients synthétiques insérées (207 clients au total).';
    ELSE
        RAISE NOTICE 'La table customers contient déjà des données.';
    END IF;
END $$;

-- Réactiver les messages NOTICE si besoin
-- SET client_min_messages TO NOTICE;

-- Message final dans les logs Docker
SELECT 'Script init.sql terminé avec succès. Base de données prête avec jeu de données synthétiques (uniquement table customers).' AS status;